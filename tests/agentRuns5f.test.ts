/**
 * FASE 5F — hardening: definição do agente como contexto autorizado, revisão consolidada (MULTI_AGENT),
 * observabilidade de uso/custo em falhas e ausência de retentativas ocultas. Nenhuma IA real.
 */

import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  AGENT_RUNS_PATH,
  InMemoryAgentRunStore,
  InMemoryNonceStore,
  PROTOCOL_VERSION,
  bodyHashHex,
  canonicalString,
  handleAgentRunHttp,
  sign,
  type AgentRunRequest,
  type AgentRunResponse,
} from "../src/agentRuns/index.js";
import { sha256Hex } from "../src/agentRuns/payload.js";
import { CostController } from "../src/orchestrator/costController.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import { loadManifestContext, parseProjectManifest } from "../src/projects/manifest.js";
import { ProviderCallError } from "../src/providers/callError.js";
import { ProviderHttpError } from "../src/providers/httpClient.js";
import type { AIProvider, HealthStatus, ProviderCapabilities, TaskInput, TaskResult } from "../src/providers/types.js";

const SECRET = "segredo-de-teste-da-fase-5f-com-32+caracteres";
const PRINCIPAL = "service:sal-intelligence-os";
const PROJECT = "sal-intelligence-os";
const NOW = new Date("2026-09-18T12:00:00.000Z");
const INVESTIGADOR = "---\nname: investigador\n---\nVocê é o Agente Investigador. Separe fato de inferência.";
const TRANSFERENCIA = "---\nname: transferencia\n---\nVocê é o especialista em malha de transferência.";

const OUTPUT = {
  facts: ["[investigador] ocupação 25,5% (ev-a)"], calculations: ["85 - 25,5 = 59,5"], inferences: ["[transferencia] retorno ocioso"],
  hypotheses: [{ statement: "demanda desequilibrada", favorable_evidence: ["ev-a"], contrary_evidence: [], missing_evidence: ["ida"], confidence: 30 }],
  contradictions: [], missing_data: ["ocupação cubada"], evidence: ["ev-a"], confidence: 30,
};

type Step = string | Error | TaskResult;

class Scripted implements AIProvider {
  readonly capabilities: ProviderCapabilities;
  readonly inputs: TaskInput[] = [];
  calls = 0;
  constructor(readonly name: AIProvider["name"], private readonly steps: Step[], cap: number | null = 0.2) {
    this.capabilities = { mayProduceExternalEffects: false, estimatedMaxCostUsd: cap ?? undefined };
  }
  async analyze(input: TaskInput): Promise<TaskResult> {
    this.inputs.push(input);
    const step = this.steps[Math.min(this.calls, this.steps.length - 1)]!;
    this.calls += 1;
    if (step instanceof Error) throw step;
    if (typeof step === "string") return { output: step, model: `${this.name}-fake`, sources: [], evidence: [], usage: { inputTokens: 10, outputTokens: 5 } };
    return step;
  }
  async healthCheck(): Promise<HealthStatus> { return { healthy: true, checkedAt: NOW.toISOString() }; }
}

async function deps(providers: AIProvider[], contextFiles: Record<string, string> = {}, extra: Record<string, unknown> = {}) {
  const repository = new InMemoryOrchestrationRepository();
  await repository.upsertProject({
    id: PROJECT, name: "SAL", repository: "x/y", defaultBranch: "main", manifest: {} as never,
    contextFiles: { "ARCHITECTURE.md": "Data Quality Gate.", "agents/investigador.md": INVESTIGADOR, "agents/transferencia.md": TRANSFERENCIA, ...contextFiles },
    missingContextFiles: [], contextSha256: "x", active: true, updatedAt: NOW.toISOString(),
  });
  await repository.upsertProjectPermission({ projectId: PROJECT, principalType: "service", principalId: "sal-intelligence-os", capability: "agent_run", createdAt: NOW.toISOString() });
  const providerManager = new ProviderManager();
  for (const provider of providers) providerManager.register(provider);
  return {
    repository, providerManager, store: new InMemoryAgentRunStore(),
    costController: new CostController({ maxCostPerTaskUsd: 100, requireConfirmationAboveUsd: 100, providerPriority: [] }),
    auth: { secret: SECRET, allowedPrincipals: [PRINCIPAL] }, nonces: new InMemoryNonceStore(), clock: () => NOW,
    allowedProviders: ["anthropic", "openai"] as const, providerCostCaps: { openai: 1 }, ...extra,
  };
}

function request(overrides: Partial<AgentRunRequest> = {}): AgentRunRequest {
  return {
    protocol_version: PROTOCOL_VERSION, request_id: randomUUID(), idempotency_key: `idem-${randomUUID()}`,
    principal: PRINCIPAL, permission: "agent_run", project: PROJECT, agent: "investigador", agent_version: "1.0.0",
    profile: "balanced", task: "Investigue a divergência sintética.",
    authorized_context: { project: PROJECT, files: ["ARCHITECTURE.md"] },
    evidence: [{ id: "ev-a", source: "sintética", period: "P1", timestamp: NOW.toISOString(), filters: {}, quality: { source_quality: "sintetica", checks: [] }, limitations: [], data: { ocupacao: 25.5 } }],
    previous_results: [], business_data: {},
    execution_limits: { timeout_seconds: 60, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 3 },
    output_contract: { kind: "investigation", schema_version: "sal.investigation-output/1.0", require_json: true },
    review_policy: { required: false, max_correction_attempts: 0 },
    agent_authority: { can_recommend: false, can_propose: false, can_approve: false, can_execute: false },
    ...overrides,
  } as AgentRunRequest;
}

async function post(dependencies: Awaited<ReturnType<typeof deps>>, body: unknown) {
  const raw = JSON.stringify(body);
  const nonce = randomUUID();
  const timestamp = NOW.toISOString();
  const signature = sign(SECRET, canonicalString({ method: "POST", path: AGENT_RUNS_PATH, timestamp, nonce, principal: PRINCIPAL, bodyHash: bodyHashHex(raw) }));
  return handleAgentRunHttp({ method: "POST", path: AGENT_RUNS_PATH, contentType: "application/json",
    authorization: `SAL-HMAC-SHA256 principal=${PRINCIPAL},timestamp=${timestamp},nonce=${nonce},signature=${signature}`, body: raw }, dependencies as never);
}

const approve = JSON.stringify({ status: "APPROVED", summary: "ok" });
const reject = JSON.stringify({ status: "REJECTED", summary: "falta evidência" });

describe("TAREFA 2 — definição do agente como contexto autorizado", () => {
  it("a definição do PRÓPRIO agente chega ao provider, com sha256 verificável e antes do contrato de autoridade", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    const dependencies = await deps([anthropic]);
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    const prompt = anthropic.inputs[0]!.prompt;
    expect(prompt).toContain(`[AGENT DEFINITION: agents/investigador.md sha256=${sha256Hex(INVESTIGADOR)}]`);
    expect(prompt).toContain("Você é o Agente Investigador.");
    expect(prompt.indexOf("[AGENT DEFINITION")).toBeLessThan(prompt.indexOf("[AGENT CONTRACT]"));
    expect(prompt).toContain("prevalece o AGENT CONTRACT");
    expect(body.context.agent_definition).toEqual({ path: "agents/investigador.md", status: "sent", sha256: sha256Hex(INVESTIGADOR) });
  });

  it("um agente NÃO recebe a definição de outro, nem via authorized_context", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    const dependencies = await deps([anthropic]);
    const body = (await post(dependencies, request({
      authorized_context: { project: PROJECT, files: ["ARCHITECTURE.md", "agents/transferencia.md"] },
    }))).body as AgentRunResponse;
    const prompt = anthropic.inputs[0]!.prompt;
    expect(prompt).not.toContain("especialista em malha de transferência");
    expect(body.context.missing_context).toEqual(["agents/transferencia.md"]); // prefixo reservado: não é contexto comum
    expect(body.context.files_sent).toEqual(["ARCHITECTURE.md"]);
  });

  it("agente sem definição registrada roda sem a seção e registra not_registered", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    const dependencies = await deps([anthropic]);
    const body = (await post(dependencies, request({ agent: "provocador" }))).body as AgentRunResponse;
    expect(anthropic.inputs[0]!.prompt).not.toContain("[AGENT DEFINITION");
    expect(body.context.agent_definition.status).toBe("not_registered");
  });

  it("definição acima do limite não é enviada (too_large), mas o hash fica registrado", async () => {
    const enorme = "x".repeat(20_001);
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    const dependencies = await deps([anthropic], { "agents/investigador.md": enorme });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(anthropic.inputs[0]!.prompt).not.toContain("[AGENT DEFINITION");
    expect(body.context.agent_definition).toEqual({ path: "agents/investigador.md", status: "too_large", sha256: sha256Hex(enorme) });
  });

  it("o payload não carrega conclusões do motor da Torre, só a evidência enviada", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    const dependencies = await deps([anthropic]);
    await post(dependencies, request());
    const prompt = anthropic.inputs[0]!.prompt;
    for (const conclusao of ["causas_provaveis", "acoes_recomendadas", "investigacoes", "agentes_consultados"]) {
      expect(prompt).not.toContain(conclusao);
    }
  });

  it("manifesto: só os arquivos listados entram (nunca a pasta inteira), sob agents/, dentro do hash", async () => {
    const root = await mkdtemp(path.join(tmpdir(), "sal-5f-"));
    await mkdir(path.join(root, "docs"), { recursive: true });
    await mkdir(path.join(root, ".claude", "agents"), { recursive: true });
    await writeFile(path.join(root, "docs", "ARCHITECTURE.md"), "arq");
    await writeFile(path.join(root, ".claude", "agents", "investigador.md"), INVESTIGADOR);
    await writeFile(path.join(root, ".claude", "agents", "transferencia.md"), TRANSFERENCIA);
    await writeFile(path.join(root, ".claude", "agents", "juridico.md"), "NÃO LISTADO");
    const manifest = parseProjectManifest([
      "version: 1", "project_id: sal-teste", "name: SAL", "repository: x/y",
      "context:", "  root: docs", "  files: [ARCHITECTURE.md]",
      "agents:", "  root: .claude/agents", "  files: [investigador.md, transferencia.md]",
      "access:", "  allowed_paths: [docs/**]", "changes: {}",
    ].join("\n"));
    const loaded = await loadManifestContext(root, manifest);
    expect(Object.keys(loaded.files).sort()).toEqual(["ARCHITECTURE.md", "agents/investigador.md", "agents/transferencia.md"]);
    expect(JSON.stringify(loaded.files)).not.toContain("NÃO LISTADO");
    const semAgentes = await loadManifestContext(root, { ...manifest, agents: undefined });
    expect(semAgentes.sha256).not.toBe(loaded.sha256); // a definição faz parte da integridade do contexto
  });

  it("manifesto recusa caminho que escapa da pasta de agentes", () => {
    const yaml = (file: string) => [
      "version: 1", "project_id: sal-teste", "name: SAL", "repository: x/y", "context:", "  files: [A.md]",
      "agents:", `  files: ["${file}"]`, "access:", "  allowed_paths: [docs/**]", "changes: {}",
    ].join("\n");
    expect(() => parseProjectManifest(yaml("../segredo.md"))).toThrow();
    expect(() => parseProjectManifest(yaml("sub/outro.md"))).toThrow();
    expect(() => parseProjectManifest(yaml("script.sh"))).toThrow();
  });
});

describe("TAREFA 1 — revisão consolidada (MULTI_AGENT)", () => {
  const consolidated = (authors: ("anthropic" | "openai")[] = ["anthropic"]) => ({
    kind: "consolidated_investigation" as const, output: OUTPUT, author_providers: authors,
    sources: [
      { agent: "investigador", status: "succeeded", run_id: "run-a" },
      { agent: "transferencia", status: "succeeded", run_id: "run-b" },
    ],
  });
  const reviewRequest = (authors?: ("anthropic" | "openai")[]) => request({
    agent: "consolidacao", review_target: consolidated(authors),
    review_policy: { required: true, max_correction_attempts: 0 },
  });

  it("revisa o conjunto: sem autor de IA, revisor ≠ autores, recebe fontes e artefato; aprovado → succeeded", async () => {
    const anthropic = new Scripted("anthropic", ["não deveria ser chamado"]);
    const openai = new Scripted("openai", [approve], null);
    const dependencies = await deps([anthropic, openai]);
    const body = (await post(dependencies, reviewRequest())).body as AgentRunResponse;
    expect(anthropic.calls).toBe(0);
    expect(openai.calls).toBe(1);
    expect(body).toMatchObject({ mode: "consolidated_review", status: "succeeded" });
    expect(body.review).toMatchObject({ status: "APPROVED", reviewer: "openai", corrections: 0 });
    expect(body.output).toEqual(OUTPUT); // a consolidação não é reescrita por IA
    const reviewPrompt = openai.inputs[0]!.prompt;
    expect(reviewPrompt).toContain("[CONSOLIDATION SOURCES]");
    expect(reviewPrompt).toContain("agente=investigador");
    expect(reviewPrompt).toContain("agente=transferencia");
    expect(reviewPrompt).toContain("[transferencia] retorno ocioso");
    expect(body.usage.map((item) => item.role)).toEqual(["reviewer"]);
  });

  it("reprovado → needs_human, sem correção (não há autor para corrigir)", async () => {
    const anthropic = new Scripted("anthropic", ["x"]);
    const openai = new Scripted("openai", [reject], null);
    const body = (await post(await deps([anthropic, openai]), reviewRequest())).body as AgentRunResponse;
    expect(body.status).toBe("needs_human");
    expect(anthropic.calls).toBe(0);
    expect(openai.calls).toBe(1);
  });

  it("se todos os providers foram autores, não há revisor independente → needs_human sem chamada", async () => {
    const anthropic = new Scripted("anthropic", ["x"]);
    const openai = new Scripted("openai", [approve], null);
    const body = (await post(await deps([anthropic, openai]), reviewRequest(["anthropic", "openai"]))).body as AgentRunResponse;
    expect(body.status).toBe("needs_human");
    expect(anthropic.calls + openai.calls).toBe(0);
  });

  it("revisão consolidada exige max_correction_attempts=0 e artefato dentro do contrato", async () => {
    const dependencies = await deps([new Scripted("openai", [approve], null)]);
    const comCorrecao = await post(dependencies, request({ agent: "consolidacao", review_target: consolidated(),
      review_policy: { required: true, max_correction_attempts: 1 } }));
    expect(comCorrecao.status).toBe(400);
    const comAutoridade = await post(dependencies, request({ agent: "consolidacao",
      review_target: { ...consolidated(), output: { ...OUTPUT, approved_decision: true } as never },
      review_policy: { required: true, max_correction_attempts: 0 } }));
    expect(comAutoridade.status).toBe(400);
  });
});

describe("TAREFA 4 — uso e custo rastreáveis mesmo em falha", () => {
  it("truncamento: tokens preservados (reported), reserva mantida, tentativa não some; fallback registrado", async () => {
    const truncated = new ProviderCallError("truncated", "truncada em max_tokens=8192", { inputTokens: 5130, outputTokens: 8192 }, "claude-sonnet-5", 1);
    const anthropic = new Scripted("anthropic", [truncated], 0.4);
    const openai = new Scripted("openai", [JSON.stringify(OUTPUT)], null);
    const body = (await post(await deps([anthropic, openai], {}, { providerCostCaps: { openai: 1, anthropic: 0.4 } }), request())).body as AgentRunResponse;
    expect(body.usage[0]).toMatchObject({ role: "author", provider: "anthropic", outcome: "truncated", usage_status: "reported",
      input_tokens: 5130, output_tokens: 8192, model: "claude-sonnet-5", reserved_cost_usd: 0.4, actual_cost_usd: "unknown" });
    expect(body.usage[1]).toMatchObject({ provider: "openai", outcome: "success", reserved_cost_usd: 1.4 });
  });

  it("timeout, rejeição 4xx e erro 5xx ficam registrados como unavailable_from_provider", async () => {
    for (const [error, outcome] of [
      [Object.assign(new Error("This operation was aborted"), { name: "AbortError" }), "timeout"],
      [new ProviderHttpError(400, { error: { param: "x" } }, "HTTP 400"), "rejected"],
      [new ProviderHttpError(503, "erro", "HTTP 503"), "provider_error"],
    ] as const) {
      const anthropic = new Scripted("anthropic", [error]);
      const dependencies = await deps([anthropic], {}, { allowedProviders: ["anthropic"] });
      const body = (await post(dependencies, request())).body as AgentRunResponse;
      expect(body.usage).toHaveLength(1);
      expect(body.usage[0]).toMatchObject({ outcome, usage_status: "unavailable_from_provider", input_tokens: "unknown", reserved_cost_usd: 0.2 });
      expect(body.usage[0]!.failure_reason).toBeTruthy();
      expect(dependencies.store.auditLog[0]?.input_tokens).toBe("unknown"); // total nunca vira soma parcial
    }
  });

  it("nenhuma retentativa oculta: toda chamada do agent-run vai com maxHttpAttempts=1", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT), JSON.stringify(OUTPUT)]);
    const openai = new Scripted("openai", [reject, approve], null);
    await post(await deps([anthropic, openai]), request({ review_policy: { required: true, max_correction_attempts: 1 } }));
    expect([...anthropic.inputs, ...openai.inputs].map((input) => input.maxHttpAttempts)).toEqual([1, 1, 1, 1]);
  });

  it("adaptação de parâmetro no provider aparece como provider_attempts=2", async () => {
    const anthropic = new Scripted("anthropic", [{ output: JSON.stringify(OUTPUT), model: "m", sources: [], evidence: [], usage: { inputTokens: 1, outputTokens: 1 }, attempts: 2 }]);
    const body = (await post(await deps([anthropic], {}, { allowedProviders: ["anthropic"] }), request())).body as AgentRunResponse;
    expect(body.usage[0]!.provider_attempts).toBe(2);
  });

  it("falha + fallback não furam o orçamento do job", async () => {
    const anthropic = new Scripted("anthropic", [new ProviderCallError("truncated", "t", { inputTokens: 1, outputTokens: 1 })], 0.4);
    const openai = new Scripted("openai", [JSON.stringify(OUTPUT)], null);
    const body = (await post(await deps([anthropic, openai], {}, { providerCostCaps: { openai: 1, anthropic: 0.4 } }), request({
      execution_limits: { timeout_seconds: 60, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 1 },
    }))).body as AgentRunResponse;
    expect(openai.calls).toBe(0); // 0,40 já reservado + 1,00 > 1,00
    expect(body.usage).toHaveLength(1);
    expect(body.status).toBe("blocked_cost");
  });
});

describe("Fase 5G — contrato de saída explícito e rejeição rastreável", () => {
  it("o payload declara que os itens de facts/calculations/... são TEXTO", async () => {
    const anthropic = new Scripted("anthropic", [JSON.stringify(OUTPUT)]);
    await post(await deps([anthropic], {}, { allowedProviders: ["anthropic"] }), request());
    const prompt = anthropic.inputs[0]!.prompt;
    expect(prompt).toContain("é UMA STRING (texto)");
    expect(prompt).toContain('"facts": ["<texto: um fato, citando o id da evidência>"]');
  });

  it("a rejeição indica o caminho do campo que quebrou o contrato", async () => {
    const objeto = { ...OUTPUT, facts: [{ fato: "estruturado", evidencia: "ev-a" }] };
    const anthropic = new Scripted("anthropic", [JSON.stringify(objeto)]);
    const outcome = await post(await deps([anthropic], {}, { allowedProviders: ["anthropic"] }), request());
    expect(outcome.status).toBe(422);
    expect((outcome.body as AgentRunResponse).output_validation.reason).toContain("facts.0: Expected string, received object");
  });
});
