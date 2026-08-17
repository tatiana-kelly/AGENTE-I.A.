import { createServer, type Server } from "node:http";
import { afterEach, describe, expect, it } from "vitest";
import { createApiHandler } from "../src/api/app.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import type { AIProvider, HealthStatus, ProviderCapabilities, TaskInput, TaskResult } from "../src/providers/types.js";

const SECRET = "test-secret-with-at-least-32-characters";
const openServers: Server[] = [];

class ApiFakeProvider implements AIProvider {
  readonly capabilities: ProviderCapabilities;
  readonly inputs: TaskInput[] = [];

  constructor(
    readonly name: AIProvider["name"],
    private readonly output: string,
    estimatedMaxCostUsd = 0,
  ) {
    this.capabilities = { mayProduceExternalEffects: false, estimatedMaxCostUsd };
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    this.inputs.push(input);
    return { output: this.output, sources: [], evidence: [] };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: new Date().toISOString() };
  }
}

afterEach(async () => {
  await Promise.all(openServers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))));
});

describe("FASE 13 — API HTTP", () => {
  it("exige bearer token em todos os endpoints", async () => {
    const { baseUrl } = await startApi();
    const response = await fetch(`${baseUrl}/orchestrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: "Analise os dados." }),
    });

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "Não autorizado." });
  });

  it("cria e consulta uma tarefa pelo ID", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const manager = new ProviderManager();
    manager.register(new ApiFakeProvider("openai", "decisão"));
    const { baseUrl } = await startApi({ repository, manager, security: { mode: "AUTONOMOUS", dryRun: false } });

    const createResponse = await apiFetch(baseUrl, "/orchestrate", {
      method: "POST",
      body: JSON.stringify({ task: "Tome uma decisão estratégica." }),
    });
    expect(createResponse.status).toBe(200);
    const created = (await createResponse.json()) as { taskId: string };

    const getResponse = await apiFetch(baseUrl, `/tasks/${created.taskId}`);
    expect(getResponse.status).toBe(200);
    const snapshot = (await getResponse.json()) as { task: { id: string; status: string } };
    expect(snapshot.task).toMatchObject({ id: created.taskId, status: "awaiting_approval" });
  });

  it("continua uma tarefa ASSISTED uma única vez e registra a aprovação", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const manager = new ProviderManager();
    const anthropic = new ApiFakeProvider("anthropic", "implementação concluída");
    manager.register(anthropic);
    const { baseUrl } = await startApi({ repository, manager, security: { mode: "ASSISTED", dryRun: false } });

    const initialResponse = await apiFetch(baseUrl, "/orchestrate", {
      method: "POST",
      body: JSON.stringify({ task: "Implemente esta arquitetura." }),
    });
    const initial = (await initialResponse.json()) as { taskId: string; requiresApproval: boolean };
    expect(initial.requiresApproval).toBe(true);
    expect(anthropic.inputs).toHaveLength(0);

    const continueResponse = await apiFetch(baseUrl, `/tasks/${initial.taskId}/continue`, {
      method: "POST",
      body: JSON.stringify({ approved: true, approvedMaxCostUsd: 0 }),
    });
    expect(continueResponse.status).toBe(200);
    const continued = (await continueResponse.json()) as { taskId: string };
    expect(continued.taskId).not.toBe(initial.taskId);
    expect(anthropic.inputs).toHaveLength(1);

    const continuedSnapshot = await repository.getTask(continued.taskId);
    expect(continuedSnapshot?.task).toMatchObject({
      continuedFromTaskId: initial.taskId,
      approval: { approved: true, source: "n8n", approvedMaxCostUsd: 0 },
    });

    const replayResponse = await apiFetch(baseUrl, `/tasks/${initial.taskId}/continue`, {
      method: "POST",
      body: JSON.stringify({ approved: true, approvedMaxCostUsd: 0 }),
    });
    expect(replayResponse.status).toBe(409);
    expect(anthropic.inputs).toHaveLength(1);
  });

  it("rejeita payload desconhecido ou excessivo", async () => {
    const { baseUrl } = await startApi({ maxBodyBytes: 40 });
    const unknownField = await apiFetch(baseUrl, "/orchestrate", {
      method: "POST",
      body: JSON.stringify({ task: "Analise.", mode: "AUTONOMOUS" }),
    });
    expect(unknownField.status).toBe(400);

    const tooLarge = await apiFetch(baseUrl, "/orchestrate", {
      method: "POST",
      body: JSON.stringify({ task: "x".repeat(100) }),
    });
    expect(tooLarge.status).toBe(413);
  });

  it("não deixa a aprovação da ação ultrapassar o valor de custo aprovado", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const manager = new ProviderManager();
    const anthropic = new ApiFakeProvider("anthropic", "feito", 0.75);
    manager.register(anthropic);
    const { baseUrl } = await startApi({ repository, manager, security: { mode: "ASSISTED", dryRun: false } });

    const initialResponse = await apiFetch(baseUrl, "/orchestrate", {
      method: "POST",
      body: JSON.stringify({ task: "Implemente esta arquitetura." }),
    });
    const initial = (await initialResponse.json()) as { taskId: string };

    const insufficientApproval = await apiFetch(baseUrl, `/tasks/${initial.taskId}/continue`, {
      method: "POST",
      body: JSON.stringify({ approved: true, approvedMaxCostUsd: 0.5 }),
    });
    const awaitingCost = (await insufficientApproval.json()) as { taskId: string; requiresApproval: boolean };
    expect(awaitingCost.requiresApproval).toBe(true);
    expect(anthropic.inputs).toHaveLength(0);

    const sufficientApproval = await apiFetch(baseUrl, `/tasks/${awaitingCost.taskId}/continue`, {
      method: "POST",
      body: JSON.stringify({ approved: true, approvedMaxCostUsd: 0.75 }),
    });
    expect(sufficientApproval.status).toBe(200);
    expect(anthropic.inputs).toHaveLength(1);
  });
});

async function startApi(options: {
  repository?: InMemoryOrchestrationRepository;
  manager?: ProviderManager;
  security?: { mode: "READ_ONLY" | "ASSISTED" | "AUTONOMOUS"; dryRun: boolean };
  maxBodyBytes?: number;
} = {}): Promise<{ baseUrl: string }> {
  const handler = createApiHandler({
    repository: options.repository ?? new InMemoryOrchestrationRepository(),
    providerManager: options.manager ?? new ProviderManager(),
    webhookSecret: SECRET,
    security: options.security ?? { mode: "READ_ONLY", dryRun: true },
    maxBodyBytes: options.maxBodyBytes,
  });
  const server = createServer((request, response) => void handler(request, response));
  openServers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Servidor de teste sem porta TCP.");
  return { baseUrl: `http://127.0.0.1:${address.port}` };
}

function apiFetch(baseUrl: string, path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${SECRET}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
}
