import { describe, expect, it, vi } from "vitest";
import { orchestrate } from "../src/orchestrator/index.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import {
  buildSupabaseRepositoryFromEnv,
  InMemoryOrchestrationRepository,
  SupabaseOrchestrationRepository,
} from "../src/persistence/index.js";
import type { AIProvider, HealthStatus, ProviderCapabilities, TaskInput, TaskResult } from "../src/providers/types.js";

class PersistenceFakeProvider implements AIProvider {
  readonly capabilities: ProviderCapabilities = { mayProduceExternalEffects: false, estimatedMaxCostUsd: 0 };

  constructor(
    readonly name: AIProvider["name"],
    private readonly output: string,
  ) {}

  async analyze(_input: TaskInput): Promise<TaskResult> {
    return { output: this.output, sources: ["fake://source"], evidence: ["e-1"] };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: new Date().toISOString() };
  }
}

describe("FASE 11 — persistência", () => {
  it("persiste tarefa, run e evidência com um ID estável", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const manager = new ProviderManager();
    manager.register(new PersistenceFakeProvider("openai", "decisão persistida"));

    const result = await orchestrate(
      { task: "Tome uma decisão estratégica.", project: "sal" },
      {
        security: { mode: "AUTONOMOUS", dryRun: false },
        providerManager: manager,
        repository,
      },
    );

    const snapshot = await repository.getTask(result.taskId);
    expect(result.taskId).toMatch(/^[0-9a-f-]{36}$/);
    expect(snapshot?.task).toMatchObject({
      id: result.taskId,
      status: "awaiting_approval",
      requiresApproval: true,
      request: { task: "Tome uma decisão estratégica.", project: "sal" },
    });
    expect(snapshot?.runs).toHaveLength(1);
    expect(snapshot?.runs[0]).toMatchObject({ taskId: result.taskId, provider: "openai", status: "success" });
    expect(snapshot?.evidence).toHaveLength(1);
    expect(snapshot?.evidence[0]).toMatchObject({ task_id: result.taskId, run_id: snapshot?.runs[0]?.id });
  });

  it("persiste a chamada do reviewer como run independente", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const manager = new ProviderManager();
    manager.register(new PersistenceFakeProvider("manus", "diagnóstico"));
    manager.register(
      new PersistenceFakeProvider("openai", '{"status":"APPROVED","summary":"resultado consistente"}'),
    );

    const result = await orchestrate(
      { task: "Analise os dados e me diga o que está acontecendo." },
      {
        security: { mode: "AUTONOMOUS", dryRun: false },
        providerManager: manager,
        repository,
      },
    );

    const snapshot = await repository.getTask(result.taskId);
    expect(snapshot?.task.status).toBe("completed");
    expect(snapshot?.runs.map(({ provider, status }) => ({ provider, status }))).toEqual([
      { provider: "manus", status: "success" },
      { provider: "openai", status: "success" },
    ]);
    expect(snapshot?.evidence).toHaveLength(2);
  });

  it("persiste bloqueio antes de qualquer chamada de provider", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const result = await orchestrate(
      { task: "Implemente e publique esta mudança." },
      { security: { mode: "READ_ONLY", dryRun: true }, repository },
    );

    const snapshot = await repository.getTask(result.taskId);
    expect(snapshot?.task.status).toBe("blocked");
    expect(snapshot?.runs[0]).toMatchObject({ status: "blocked" });
    expect(snapshot?.evidence[0]).toMatchObject({ status: "blocked", task_id: result.taskId });
  });

  it("não cria adapter com configuração Supabase parcial", () => {
    expect(() => buildSupabaseRepositoryFromEnv({ SUPABASE_URL: "https://example.supabase.co" })).toThrow(
      /devem ser configuradas juntas/,
    );
    expect(buildSupabaseRepositoryFromEnv({})).toBeUndefined();
  });

  it("envia writes ao schema próprio pela API REST do Supabase", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 201 }));
    const repository = new SupabaseOrchestrationRepository({
      url: "https://example.supabase.co",
      serviceRoleKey: "test-service-role-key",
      fetchImpl: fetchMock,
    });
    const now = new Date().toISOString();

    await repository.createTask({
      id: "10000000-0000-4000-8000-000000000001",
      request: { task: "Analise os dados." },
      status: "received",
      classification: {
        skills: ["data-analysis"],
        effectLevel: "READ",
        requiresGoogleWorkspace: false,
        requiresInvestigation: false,
        requiresImplementation: false,
        requiresDecision: false,
        requiresAdversarialReview: false,
        rationale: "teste",
      },
      routing: { primary: "openai", reason: "teste", confidence: 1 },
      plan: { mode: "ONE_AGENT", steps: [{ provider: "openai", purpose: "analisar" }] },
      executionMode: "READ_ONLY",
      dryRun: true,
      requiresApproval: false,
      createdAt: now,
      updatedAt: now,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://example.supabase.co/rest/v1/ai_tasks");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      apikey: "test-service-role-key",
      Authorization: "Bearer test-service-role-key",
    });
    expect(JSON.parse(init.body as string)).toMatchObject({ task_text: "Analise os dados.", status: "received" });
  });
});
