/**
 * FASE 5E — revisão independente (Anthropic → OpenAI), portão único de custo/segurança para TODA chamada,
 * teto de custo específico do agent-run e autenticação mútua (identidade + resposta assinada).
 * Nenhuma chamada real de IA: providers falsos contam as próprias invocações.
 */

import { randomUUID } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  AGENT_RUNS_IDENTITY_PATH,
  AGENT_RUNS_PATH,
  InMemoryAgentRunStore,
  InMemoryNonceStore,
  PROTOCOL_HEADER,
  PROTOCOL_VERSION,
  RESPONSE_SIGNATURE_HEADER,
  bodyHashHex,
  canonicalString,
  handleAgentRunHttp,
  identityCanonical,
  responseCanonical,
  sign,
  type AgentRunRequest,
  type AgentRunResponse,
} from "../src/agentRuns/index.js";
import { buildAgentRunDependenciesFromEnv, parseAgentRunCostCaps } from "../src/agentRuns/factory.js";
import { CostController } from "../src/orchestrator/costController.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import type { AIProvider, HealthStatus, ProviderCapabilities, TaskInput, TaskResult } from "../src/providers/types.js";

const SECRET = "segredo-de-teste-da-fase-5e-com-32+chars";
const PRINCIPAL = "service:sal-intelligence-os";
const PROJECT = "sal-intelligence-os";
const NOW = new Date("2026-09-18T12:00:00.000Z");

const CORRECT = {
  facts: ["FONTE-A=1000 (ev-a)", "FONTE-B=940 (ev-b)"],
  calculations: ["1000 - 940 = 60"],
  inferences: ["possível perda de captura em FONTE-B"],
  hypotheses: [{ statement: "FONTE-B incompleta", favorable_evidence: ["completude 90%"], contrary_evidence: [], missing_evidence: ["itens"], confidence: 40 }],
  contradictions: [],
  missing_data: ["detalhe por item"],
  evidence: ["ev-a", "ev-b"],
  confidence: 40,
};
const WRONG = { ...CORRECT, calculations: ["1000 - 940 = 80"] }; // cálculo errado de propósito

type Script = string | Error | ((input: TaskInput) => string);

/** Provider falso com roteiro: cada chamada consome o próximo item (o último se repete). */
class ScriptedProvider implements AIProvider {
  readonly capabilities: ProviderCapabilities;
  readonly inputs: TaskInput[] = [];
  calls = 0;

  constructor(
    readonly name: AIProvider["name"],
    private readonly script: Script[],
    estimatedMaxCostUsd: number | null = 0.01, // null = provider SEM teto declarado (undefined viraria o padrão)
    private readonly usage?: { inputTokens: number; outputTokens: number },
  ) {
    this.capabilities = { mayProduceExternalEffects: false, estimatedMaxCostUsd: estimatedMaxCostUsd ?? undefined };
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    this.inputs.push(input);
    const step = this.script[Math.min(this.calls, this.script.length - 1)]!;
    this.calls += 1;
    if (step instanceof Error) throw step;
    const output = typeof step === "function" ? step(input) : step;
    return { output, model: `${this.name}-fake`, sources: [], evidence: [], usage: this.usage };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: NOW.toISOString() };
  }
}

async function deps(providers: AIProvider[], extra: Record<string, unknown> = {}) {
  const repository = new InMemoryOrchestrationRepository();
  await repository.upsertProject({
    id: PROJECT, name: "SAL Intelligence OS", repository: "tatiana-kelly/sal-intelligence-os", defaultBranch: "main",
    manifest: {} as never, contextFiles: { "ARCHITECTURE.md": "Data Quality Gate valida comparabilidade." },
    missingContextFiles: [], contextSha256: "x", active: true, updatedAt: NOW.toISOString(),
  });
  await repository.upsertProjectPermission({
    projectId: PROJECT, principalType: "service", principalId: "sal-intelligence-os", capability: "agent_run", createdAt: NOW.toISOString(),
  });
  const providerManager = new ProviderManager();
  for (const provider of providers) providerManager.register(provider);
  return {
    repository, providerManager, store: new InMemoryAgentRunStore(),
    costController: new CostController({ maxCostPerTaskUsd: 100, requireConfirmationAboveUsd: 100, providerPriority: [] }),
    auth: { secret: SECRET, allowedPrincipals: [PRINCIPAL] }, nonces: new InMemoryNonceStore(), clock: () => NOW,
    allowedProviders: ["anthropic", "openai"] as const,
    ...extra,
  };
}

function request(overrides: Partial<AgentRunRequest> = {}): AgentRunRequest {
  return {
    protocol_version: PROTOCOL_VERSION, request_id: randomUUID(), idempotency_key: `idem-${randomUUID()}`,
    principal: PRINCIPAL, permission: "agent_run", project: PROJECT, agent: "investigador", agent_version: "1.0.0",
    profile: "balanced", task: "Investigue a divergência sintética entre FONTE-A e FONTE-B.",
    authorized_context: { project: PROJECT, files: ["ARCHITECTURE.md"] },
    evidence: [
      { id: "ev-a", source: "FONTE-A", period: "P1", timestamp: NOW.toISOString(), filters: {}, quality: { source_quality: "sintetica", checks: [] }, limitations: [], data: { registros: 1000 } },
      { id: "ev-b", source: "FONTE-B", period: "P1", timestamp: NOW.toISOString(), filters: {}, quality: { source_quality: "sintetica", checks: [] }, limitations: [], data: { registros: 940 } },
    ],
    previous_results: [], business_data: {},
    execution_limits: { timeout_seconds: 30, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 3 },
    output_contract: { kind: "investigation", schema_version: "sal.investigation-output/1.0", require_json: true },
    review_policy: { required: true, max_correction_attempts: 1 },
    agent_authority: { can_recommend: false, can_propose: false, can_approve: false, can_execute: false },
    ...overrides,
  } as AgentRunRequest;
}

function authHeader(body: string, path = AGENT_RUNS_PATH, nonce = randomUUID()) {
  const timestamp = NOW.toISOString();
  const signature = sign(SECRET, canonicalString({ method: "POST", path, timestamp, nonce, principal: PRINCIPAL, bodyHash: bodyHashHex(body) }));
  return { header: `SAL-HMAC-SHA256 principal=${PRINCIPAL},timestamp=${timestamp},nonce=${nonce},signature=${signature}`, nonce };
}

async function post(dependencies: Awaited<ReturnType<typeof deps>>, body: unknown, path = AGENT_RUNS_PATH) {
  const raw = JSON.stringify(body);
  const { header, nonce } = authHeader(raw, path);
  const outcome = await handleAgentRunHttp(
    { method: "POST", path, contentType: "application/json", authorization: header, body: raw },
    dependencies as never,
  );
  return { ...outcome, nonce };
}

const approve = JSON.stringify({ status: "APPROVED", summary: "investigação consistente com as evidências" });
const reject = JSON.stringify({ status: "REJECTED", summary: "cálculo errado: 1000 - 940 = 60, não 80" });

describe("revisão independente Anthropic → OpenAI", () => {
  it("a) resultado correto → revisor aprova → succeeded, com uso de autor e revisor registrado", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2, { inputTokens: 100, outputTokens: 50 });
    const openai = new ScriptedProvider("openai", [approve], null, { inputTokens: 80, outputTokens: 20 });
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;

    expect(body.status).toBe("succeeded");
    expect(body.review).toMatchObject({ required: true, reviewed: true, status: "APPROVED", reviewer: "openai", corrections: 0 });
    expect(body.usage.map((item) => `${item.role}:${item.provider}`)).toEqual(["author:anthropic", "reviewer:openai"]);
    expect(body.usage[1]).toMatchObject({ estimated_cost_usd: 1, reserved_cost_usd: 1.2, actual_cost_usd: "unknown", total_tokens: 100 });

    // o revisor recebeu investigação + contexto autorizado + evidências + lista de verificação
    const reviewPrompt = openai.inputs[0]!.prompt;
    expect(reviewPrompt).toContain("[REVIEW CHECKLIST]");
    expect(reviewPrompt).toContain("[ARQUIVO: ARCHITECTURE.md]");
    expect(reviewPrompt).toContain("source=FONTE-B");
    expect(reviewPrompt).toContain("1000 - 940 = 60");
    expect(openai.inputs[0]!.modelProfile).toBe("critical");
  });

  it("b) resultado incorreto → revisor reprova → autor corrige → revisor aprova a versão corrigida", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [reject, approve], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;

    expect(body.status).toBe("succeeded");
    expect(body.review).toMatchObject({ status: "APPROVED", corrections: 1 });
    expect(body.output?.calculations).toEqual(["1000 - 940 = 60"]); // a versão corrigida é a entregue
    expect(body.usage.map((item) => item.role)).toEqual(["author", "reviewer", "correction", "reviewer"]);
    expect(anthropic.inputs[1]!.prompt).toContain("cálculo errado"); // o feedback do revisor chegou ao autor
  });

  it("b2) revisor reprova e a correção esgota o limite → needs_human, nunca sucesso", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG)], 0.2);
    const openai = new ScriptedProvider("openai", [reject], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(body.review.status).toBe("REJECTED");
    expect(body.status).toBe("needs_human");
  });

  it("c) revisor com resposta inválida → fail closed (needs_human)", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", ["parece bom pra mim"], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(body.review.status).toBe("NEEDS_HUMAN");
    expect(body.status).toBe("needs_human");
  });

  it("d) revisor tentando exercer autoridade → revisão anulada (needs_human)", async () => {
    for (const field of ["approved_decision", "execute_action", "verified_ok"]) {
      const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
      const openai = new ScriptedProvider("openai", [JSON.stringify({ status: "APPROVED", summary: "ok", [field]: true })], undefined);
      const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
      const body = (await post(dependencies, request())).body as AgentRunResponse;
      expect(body.review.authority_violation).toBe(true);
      expect(body.review.status).toBe("NEEDS_HUMAN");
      expect(body.review.summary).toContain(field);
      expect(body.status).toBe("needs_human");
    }
  });

  it("e) segundo provider indisponível → revisão humana, nunca aprovação silenciosa", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
    const falho = new ScriptedProvider("openai", [new Error("openai fora do ar")], null);
    const dependencies = await deps([anthropic, falho], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(body.review.status).toBe("NEEDS_HUMAN");
    expect(body.status).toBe("needs_human");

    const semOpenai = await deps([new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2)]);
    const body2 = (await post(semOpenai, request())).body as AgentRunResponse;
    expect(body2.status).toBe("needs_human");
  });

  it("e2) autor primário cai → OpenAI assume como autor → não revisa a si mesma (needs_human)", async () => {
    const anthropic = new ScriptedProvider("anthropic", [new Error("anthropic fora do ar")], 0.2);
    const openai = new ScriptedProvider("openai", [JSON.stringify(CORRECT)], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(body.providers).toMatchObject({ fallback_triggered: true, fallback_provider: "openai" });
    expect(body.review.status).toBe("NEEDS_HUMAN"); // autorrevisão bloqueada pelo ciclo existente
    expect(openai.calls).toBe(1);
  });
});

describe("portão único de custo e segurança (autor, revisor e correção)", () => {
  it("revisor sem teto de custo no agent-run é bloqueado ANTES de ser chamado", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [approve], null); // sem teto e sem providerCostCaps
    const dependencies = await deps([anthropic, openai]);
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(openai.calls).toBe(0);
    expect(body.review.status).toBe("NEEDS_HUMAN");
    expect(body.review.summary).toContain("Revisor bloqueado");
  });

  it("revisão que estouraria o orçamento do job é bloqueada, e o custo nunca vira zero", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [approve], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request({
      execution_limits: { timeout_seconds: 30, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 1 },
    }))).body as AgentRunResponse;
    expect(openai.calls).toBe(0); // 0,20 + 1,00 > 1,00
    expect(body.status).toBe("needs_human");
    expect(body.usage.every((item) => item.actual_cost_usd === "unknown")).toBe(true);
  });

  it("correção também passa pelo portão: sem orçamento, não corrige e escala", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [reject, approve], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request({
      execution_limits: { timeout_seconds: 30, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 1.3 },
    }))).body as AgentRunResponse;
    expect(anthropic.calls).toBe(1); // 0,20 + 1,00 + 0,20 > 1,30: correção barrada
    expect(body.status).toBe("needs_human");
  });

  it("Manus e Gemini nunca são autor nem revisor", async () => {
    const manus = new ScriptedProvider("manus", [approve], 0.01);
    const gemini = new ScriptedProvider("gemini", [approve], 0.01);
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2);
    const dependencies = await deps([manus, gemini, anthropic], { allowedProviders: ["anthropic"] });
    await post(dependencies, request());
    expect(manus.calls + gemini.calls).toBe(0);
  });
});

describe("teto de custo próprio do agent-run", () => {
  it("AGENT_RUN_<PROVIDER>_MAX_COST_PER_CALL_USD só aceita valores válidos dentro do contrato", () => {
    expect(parseAgentRunCostCaps({ AGENT_RUN_OPENAI_MAX_COST_PER_CALL_USD: "1" })).toEqual({ openai: 1 });
    expect(parseAgentRunCostCaps({ AGENT_RUN_OPENAI_MAX_COST_PER_CALL_USD: "50" })).toEqual({}); // acima de US$ 10
    expect(parseAgentRunCostCaps({ AGENT_RUN_OPENAI_MAX_COST_PER_CALL_USD: "abc" })).toEqual({});
    expect(parseAgentRunCostCaps({ AGENT_RUN_MANUS_MAX_COST_PER_CALL_USD: "1" })).toEqual({}); // Manus não existe aqui
  });

  it("habilitar OpenAI no agent-run não mexe no teto do /orchestrate", () => {
    const env = { AGENT_RUN_HMAC_SECRET: "x".repeat(40), AGENT_RUN_OPENAI_MAX_COST_PER_CALL_USD: "1" };
    const built = buildAgentRunDependenciesFromEnv(new InMemoryOrchestrationRepository(), new ProviderManager(), env)!;
    expect(built.providerCostCaps).toEqual({ openai: 1 });
    expect(env).not.toHaveProperty("OPENAI_MAX_COST_PER_CALL_USD"); // a variável do /orchestrate segue intocada
  });
});

describe("autenticação mútua: identidade e resposta assinada", () => {
  it("identidade: devolve prova HMAC do desafio, e a resposta vem assinada", async () => {
    const dependencies = await deps([]);
    const challenge = randomUUID();
    const outcome = await post(dependencies, { challenge }, AGENT_RUNS_IDENTITY_PATH);
    expect(outcome.status).toBe(200);
    const body = outcome.body as unknown as { proof: string; service: string; protocol_version: string };
    expect(body.service).toBe("ai-orchestrator");
    expect(body.proof).toBe(sign(SECRET, identityCanonical(challenge)));
    expect(outcome.headers[PROTOCOL_HEADER]).toBe(PROTOCOL_VERSION);
    expect(outcome.headers[RESPONSE_SIGNATURE_HEADER]).toBe(sign(SECRET, responseCanonical(outcome.nonce, JSON.stringify(outcome.body))));
  });

  it("identidade não aceita corpo fora do contrato nem requisição sem assinatura", async () => {
    const dependencies = await deps([]);
    expect((await post(dependencies, { challenge: "curto" }, AGENT_RUNS_IDENTITY_PATH)).status).toBe(400);
    const anonima = await handleAgentRunHttp(
      { method: "POST", path: AGENT_RUNS_IDENTITY_PATH, contentType: "application/json", authorization: undefined, body: "{}" },
      dependencies as never,
    );
    expect(anonima.status).toBe(401);
    expect(anonima.headers[RESPONSE_SIGNATURE_HEADER]).toBeUndefined(); // sem autenticação, nada é assinado
  });

  it("toda resposta a requisição autenticada é assinada — inclusive erros", async () => {
    const dependencies = await deps([new ScriptedProvider("anthropic", ["texto sem json"], 0.2)], { allowedProviders: ["anthropic"] });
    const outcome = await post(dependencies, request({ review_policy: { required: false, max_correction_attempts: 0 } }));
    expect(outcome.status).toBe(422);
    expect(outcome.headers[RESPONSE_SIGNATURE_HEADER]).toBe(sign(SECRET, responseCanonical(outcome.nonce, JSON.stringify(outcome.body))));
  });
});

describe("auditoria consistente com revisão", () => {
  it("provider/modelo/tentativa são do autor; tokens são o total do job; reprovações ficam registradas", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2, { inputTokens: 100, outputTokens: 50 });
    const openai = new ScriptedProvider("openai", [reject, approve], null, { inputTokens: 80, outputTokens: 20 });
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    const [record] = dependencies.store.auditLog;

    expect(record).toMatchObject({ provider: "anthropic", model: "anthropic-fake", attempt: 2, review_status: "APPROVED" });
    expect(record?.input_tokens).toBe(100 + 80 + 100 + 80);
    expect(record?.output_tokens).toBe(50 + 20 + 50 + 20);
    expect(record?.cost_usd).toBe("unknown");
    expect(body.review.rejections).toEqual(["cálculo errado: 1000 - 940 = 60, não 80"]);
  });

  it("se alguma chamada não informa tokens, o total é unknown — nunca uma soma parcial", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(CORRECT)], 0.2, { inputTokens: 100, outputTokens: 50 });
    const openai = new ScriptedProvider("openai", [approve], null); // revisor sem usage
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    await post(dependencies, request());
    expect(dependencies.store.auditLog[0]?.input_tokens).toBe("unknown");
  });
});

describe("prazo do contrato chega ao provider (Fase 6)", () => {
  it("autor, revisor e correção recebem timeoutMs = timeout_seconds do contrato", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [reject, approve], null);
    const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1 } });
    await post(dependencies, request({ execution_limits: { timeout_seconds: 180, max_attempts: 3, max_cost_usd_per_call: 1, max_cost_usd_per_job: 3 } }));
    expect(anthropic.inputs.map((input) => input.timeoutMs)).toEqual([180_000, 180_000]); // autor + correção
    expect(openai.inputs.map((input) => input.timeoutMs)).toEqual([180_000, 180_000]); // duas revisões
  });
});

describe("limite de saída do agent-run (Fase 6)", () => {
  it("autor e correção Anthropic recebem o limite do agent-run; revisor sem limite próprio usa o do provider", async () => {
    const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2);
    const openai = new ScriptedProvider("openai", [reject, approve], null);
    const dependencies = await deps([anthropic, openai], {
      providerCostCaps: { openai: 1, anthropic: 0.4 }, providerMaxOutputTokens: { anthropic: 8192 },
    });
    const body = (await post(dependencies, request())).body as AgentRunResponse;
    expect(anthropic.inputs.map((input) => input.maxOutputTokens)).toEqual([8192, 8192]);
    expect(openai.inputs.map((input) => input.maxOutputTokens)).toEqual([undefined, undefined]);
    expect(body.usage[0]).toMatchObject({ role: "author", estimated_cost_usd: 0.4 }); // teto do agent-run, não o do provider
  });

  it("AGENT_RUN_<PROVIDER>_MAX_OUTPUT_TOKENS aceita só inteiros positivos até o teto técnico", async () => {
    const { parseAgentRunOutputTokens } = await import("../src/agentRuns/factory.js");
    expect(parseAgentRunOutputTokens({ AGENT_RUN_ANTHROPIC_MAX_OUTPUT_TOKENS: "8192" })).toEqual({ anthropic: 8192 });
    expect(parseAgentRunOutputTokens({ AGENT_RUN_ANTHROPIC_MAX_OUTPUT_TOKENS: "999999" })).toEqual({});
    expect(parseAgentRunOutputTokens({ AGENT_RUN_ANTHROPIC_MAX_OUTPUT_TOKENS: "81.5" })).toEqual({});
    expect(parseAgentRunOutputTokens({ AGENT_RUN_MANUS_MAX_OUTPUT_TOKENS: "8192" })).toEqual({});
  });
});

it("reserva acumulada não carrega ruído de ponto flutuante (0,4 + 1 + 0,4 = 1,8)", async () => {
  const anthropic = new ScriptedProvider("anthropic", [JSON.stringify(WRONG), JSON.stringify(CORRECT)], 0.2);
  const openai = new ScriptedProvider("openai", [reject, approve], null);
  const dependencies = await deps([anthropic, openai], { providerCostCaps: { openai: 1, anthropic: 0.4 } });
  const body = (await post(dependencies, request())).body as AgentRunResponse;
  expect(body.usage.map((item) => item.reserved_cost_usd)).toEqual([0.4, 1.4, 1.8, 2.8]);
});
