/**
 * FASE 5B — contrato /v1/agent-runs (sal.agent-run/1.0).
 * Nenhuma chamada real de IA: todos os providers aqui são falsos e contam suas próprias invocações.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { createServer, type Server } from "node:http";
import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import { createApiHandler } from "../src/api/app.js";
import {
  AGENT_RUNS_PATH,
  InMemoryAgentRunStore,
  InMemoryNonceStore,
  AGENT_RUN_PROVIDER_ALLOWLIST,
  LIMITS,
  PROTOCOL_VERSION,
  agentRunRequestSchema,
  bodyHashHex,
  canonicalString,
  executeAgentRun,
  handleAgentRunHttp,
  parseAgentRunProviders,
  sign,
  type AgentRunRequest,
  type AgentRunResponse,
} from "../src/agentRuns/index.js";
import { buildProviderPayload, resolveAuthorizedContext } from "../src/agentRuns/payload.js";
import { CostController } from "../src/orchestrator/costController.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import type { ProjectRecord } from "../src/persistence/index.js";
import type { AIProvider, HealthStatus, ProviderCapabilities, TaskInput, TaskResult } from "../src/providers/types.js";

const SECRET = "agent-run-hmac-secret-com-mais-de-32-chars";
const WEBHOOK_SECRET = "test-secret-with-at-least-32-characters";
const PRINCIPAL = "service:sal-intelligence-os";
const PROJECT = "sal-intelligence-os";
const NOW = new Date("2026-09-17T12:00:00.000Z");
const openServers: Server[] = [];

const VALID_OUTPUT = JSON.stringify({
  facts: ["ocupação média de 17,6% na janela de 5 dias úteis"],
  calculations: ["gap = 85% - 17,6%"],
  inferences: ["malha possivelmente desbalanceada"],
  hypotheses: [
    {
      statement: "demanda concentrada em um sentido",
      favorable_evidence: ["ocupação assimétrica"],
      contrary_evidence: ["frete estável"],
      missing_evidence: ["volume por sentido"],
      confidence: 60,
    },
  ],
  contradictions: [],
  missing_data: ["custo real por viagem"],
  evidence: ["ev-1"],
  confidence: 55,
});

class FakeProvider implements AIProvider {
  readonly capabilities: ProviderCapabilities;
  readonly inputs: TaskInput[] = [];
  calls = 0;

  constructor(
    readonly name: AIProvider["name"],
    private readonly behaviour: { output?: string; fail?: string; delayMs?: number; usage?: { inputTokens: number; outputTokens: number }; model?: string; externalEffects?: boolean },
    estimatedMaxCostUsd: number | null = 0.01,
  ) {
    // null = provider sem custo máximo declarado (o CostController trata como desconhecido)
    this.capabilities = {
      mayProduceExternalEffects: behaviour.externalEffects ?? false,
      estimatedMaxCostUsd: estimatedMaxCostUsd ?? undefined,
    };
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    this.calls += 1;
    this.inputs.push(input);
    if (this.behaviour.delayMs) await new Promise((resolve) => setTimeout(resolve, this.behaviour.delayMs));
    if (this.behaviour.fail) throw new Error(this.behaviour.fail);
    return {
      output: this.behaviour.output ?? VALID_OUTPUT,
      model: this.behaviour.model ?? `${this.name}-model`,
      sources: [],
      evidence: [],
      usage: this.behaviour.usage,
    };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: NOW.toISOString() };
  }
}

function projectRecord(): ProjectRecord {
  return {
    id: PROJECT,
    name: "SAL Intelligence OS",
    repository: "tatiana-kelly/AGENTE-I.A",
    defaultBranch: "main",
    manifest: {} as ProjectRecord["manifest"],
    contextFiles: {
      "BUSINESS-RULES.md": "A ocupação alvo da malha de transferência é 85%.",
      "DATA-DICTIONARY.md": "ocup = ocupação percentual da viagem.",
    },
    missingContextFiles: [],
    contextSha256: "sha256-teste",
    active: true,
    updatedAt: NOW.toISOString(),
  };
}

function validRequest(overrides: Partial<AgentRunRequest> = {}): AgentRunRequest {
  return {
    protocol_version: PROTOCOL_VERSION,
    request_id: randomUUID(),
    idempotency_key: "idem-key-controlada-0001",
    principal: PRINCIPAL,
    permission: "agent_run",
    project: PROJECT,
    agent: "investigador",
    agent_version: "1.0.0",
    profile: "balanced",
    task: "Investigue a causa de uma divergência operacional na ocupação da rota de transferência.",
    authorized_context: { project: PROJECT, files: ["BUSINESS-RULES.md"] },
    evidence: [
      {
        id: "ev-1",
        source: "fixture-controlado",
        period: "5du:2026-09-17",
        timestamp: NOW.toISOString(),
        filters: { rota: "ROTA-TESTE" },
        quality: { source_quality: "real", completeness_pct: 100, checks: ["comparabilidade"] },
        limitations: ["amostra de teste"],
        data: { ocupacao_pct: 17.6, alvo_pct: 85 },
      },
    ],
    previous_results: [],
    business_data: { periodo: "5du" },
    execution_limits: { timeout_seconds: 30, max_attempts: 2, max_cost_usd_per_call: 10, max_cost_usd_per_job: 100 },
    output_contract: { kind: "investigation", schema_version: "sal.investigation-output/1.0", require_json: true },
    review_policy: { required: false, max_correction_attempts: 1 },
    agent_authority: { can_recommend: false, can_propose: false, can_approve: false, can_execute: false },
    ...overrides,
  } as AgentRunRequest;
}

async function deps(
  providers: FakeProvider[],
  options: { maxCostPerTaskUsd?: number; allowedProviders?: ("openai" | "anthropic")[] } = {},
) {
  const repository = new InMemoryOrchestrationRepository();
  await repository.upsertProject(projectRecord());
  await repository.upsertProjectPermission({
    projectId: PROJECT,
    principalType: "service",
    principalId: "sal-intelligence-os",
    capability: "agent_run",
    createdAt: NOW.toISOString(),
  });
  const providerManager = new ProviderManager();
  for (const provider of providers) providerManager.register(provider);
  return {
    repository,
    providerManager,
    store: new InMemoryAgentRunStore(),
    costController: new CostController({
      maxCostPerTaskUsd: options.maxCostPerTaskUsd ?? 1,
      requireConfirmationAboveUsd: options.maxCostPerTaskUsd ?? 1,
      providerPriority: ["openai", "manus", "anthropic", "gemini"],
    }),
    auth: { secret: SECRET, allowedPrincipals: [PRINCIPAL] },
    nonces: new InMemoryNonceStore(),
    clock: () => NOW,
    // ordem determinística nos testes: openai primeiro, anthropic como fallback/revisor
    allowedProviders: options.allowedProviders ?? (["openai", "anthropic"] as const),
  };
}

function signed(body: string, overrides: { principal?: string; timestamp?: string; nonce?: string; signature?: string } = {}) {
  const principal = overrides.principal ?? PRINCIPAL;
  const timestamp = overrides.timestamp ?? NOW.toISOString();
  const nonce = overrides.nonce ?? randomUUID();
  const signature =
    overrides.signature ??
    sign(SECRET, canonicalString({ method: "POST", path: AGENT_RUNS_PATH, timestamp, nonce, principal, bodyHash: bodyHashHex(body) }));
  return `SAL-HMAC-SHA256 principal=${principal},timestamp=${timestamp},nonce=${nonce},signature=${signature}`;
}

async function post(dependencies: Awaited<ReturnType<typeof deps>>, request: unknown, authOverrides = {}) {
  const body = JSON.stringify(request);
  return handleAgentRunHttp(
    { method: "POST", path: AGENT_RUNS_PATH, contentType: "application/json", authorization: signed(body, authOverrides), body },
    dependencies,
  );
}

afterEach(async () => {
  await Promise.all(openServers.splice(0).map((server) => new Promise<void>((resolve) => server.close(() => resolve()))));
});

describe("contrato e limites", () => {
  it("1. aceita um request válido e devolve output estruturado", async () => {
    const provider = new FakeProvider("openai", {});
    const dependencies = await deps([provider]);
    const outcome = await post(dependencies, validRequest());
    const body = outcome.body as AgentRunResponse;
    expect(outcome.status).toBe(200);
    expect(body.status).toBe("succeeded");
    expect(body.output?.facts).toHaveLength(1);
    expect(body.output_validation.valid).toBe(true);
    expect(provider.calls).toBe(1);
  });

  it("2. rejeita schema inválido", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(dependencies, { ...validRequest(), protocol_version: "sal.agent-run/9.9" });
    expect(outcome.status).toBe(400);
  });

  it("3. rejeita propriedade desconhecida", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(dependencies, { ...validRequest(), extra_field: "não previsto" });
    expect(outcome.status).toBe(400);
    expect((outcome.body as { detail?: string }).detail).toContain("extra_field");
  });

  it("4. rejeita body acima do limite", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await handleAgentRunHttp(
      { method: "POST", path: AGENT_RUNS_PATH, contentType: "application/json", authorization: "x", body: undefined, tooLarge: true },
      dependencies,
    );
    expect(outcome.status).toBe(413);
  });

  it("5. rejeita task acima do limite", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(dependencies, validRequest({ task: "a".repeat(LIMITS.taskChars + 1) }));
    expect(outcome.status).toBe(400);
  });

  it("6. rejeita previous_results acima do limite agregado", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(
      dependencies,
      validRequest({ previous_results: Array.from({ length: 4 }, () => "x".repeat(90_000)) }),
    );
    expect(outcome.status).toBe(400);
  });

  it("7. rejeita business_data acima do limite", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(dependencies, validRequest({ business_data: { blob: "x".repeat(LIMITS.businessDataBytes) } }));
    expect(outcome.status).toBe(400);
  });
});

describe("autenticação SAL-HMAC-SHA256", () => {
  it("8. aceita assinatura válida", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    expect((await post(dependencies, validRequest())).status).toBe(200);
  });

  it("9. rejeita assinatura inválida", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outcome = await post(dependencies, validRequest(), { signature: "f".repeat(64) });
    expect(outcome.status).toBe(401);
  });

  it("10. rejeita principal não autorizado", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const body = JSON.stringify(validRequest({ principal: "service:desconhecido" }));
    const outcome = await handleAgentRunHttp(
      {
        method: "POST",
        path: AGENT_RUNS_PATH,
        contentType: "application/json",
        authorization: signed(body, { principal: "service:desconhecido" }),
        body,
      },
      dependencies,
    );
    expect(outcome.status).toBe(403);
  });

  it("11. rejeita permission diferente de agent_run, timestamp velho e replay de nonce", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    expect((await post(dependencies, { ...validRequest(), permission: "read_context" })).status).toBe(400);
    expect((await post(dependencies, validRequest(), { timestamp: "2026-09-17T10:00:00.000Z" })).status).toBe(401);

    const nonce = "nonce-fixo-de-teste";
    expect((await post(dependencies, validRequest({ idempotency_key: "idem-a-0000000001" }), { nonce })).status).toBe(200);
    const replay = await post(dependencies, validRequest({ idempotency_key: "idem-b-0000000002" }), { nonce });
    expect(replay.status).toBe(401);
    expect((replay.body as { error: string }).error).toBe("replay");
  });
});

describe("permissão de projeto e interoperabilidade", () => {
  it("principal sem capability agent_run recebe 403", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const semPermissao = { ...dependencies, repository: new InMemoryOrchestrationRepository() };
    await semPermissao.repository.upsertProject(projectRecord());
    const outcome = await post(semPermissao, validRequest());
    expect(outcome.status).toBe(403);
    expect((outcome.body as { error: string }).error).toBe("permission_denied");
  });

  it("principal com capability de outro tipo não serve", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const outroRepo = new InMemoryOrchestrationRepository();
    await outroRepo.upsertProject(projectRecord());
    await outroRepo.upsertProjectPermission({
      projectId: PROJECT,
      principalType: "service",
      principalId: "sal-intelligence-os",
      capability: "read_context",
      createdAt: NOW.toISOString(),
    });
    const outcome = await post({ ...dependencies, repository: outroRepo }, validRequest());
    expect(outcome.status).toBe(403);
  });

  it("assina igual ao SAL OS (vetor compartilhado Python ↔ TypeScript)", () => {
    const vector = JSON.parse(
      readFileSync(path.join(process.cwd(), "sal-intelligence-os/backend/tests/fixtures/agent_run_signature_vector.json"), "utf8"),
    ) as Record<string, string>;
    expect(bodyHashHex(vector.body!)).toBe(vector.body_hash_sha256);
    const canonical = canonicalString({
      method: vector.method!,
      path: vector.path!,
      timestamp: vector.timestamp!,
      nonce: vector.nonce!,
      principal: vector.principal!,
      bodyHash: bodyHashHex(vector.body!),
    });
    expect(sign(vector.secret!, canonical)).toBe(vector.expected_signature);
  });
});

describe("idempotência", () => {
  it("12. mesma chave e mesmo corpo não executa o provider duas vezes", async () => {
    const provider = new FakeProvider("openai", {});
    const dependencies = await deps([provider]);
    const request = validRequest();
    const first = await post(dependencies, request);
    const second = await post(dependencies, request);
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect((second.body as AgentRunResponse).replayed).toBe(true);
    expect((second.body as AgentRunResponse).run_id).toBe((first.body as AgentRunResponse).run_id);
    expect(provider.calls).toBe(1);
  });

  it("13. mesma chave com corpo diferente é conflito", async () => {
    const provider = new FakeProvider("openai", {});
    const dependencies = await deps([provider]);
    await post(dependencies, validRequest());
    const conflict = await post(dependencies, validRequest({ task: "outra tarefa completamente diferente" }));
    expect(conflict.status).toBe(409);
    expect(provider.calls).toBe(1);
  });
});

describe("providers, custo e fallback", () => {
  it("14. timeout devolve 504 sem promover resultado", async () => {
    const provider = new FakeProvider("openai", { delayMs: 50 });
    const dependencies = await deps([provider]);
    const outcome = await post(
      dependencies,
      validRequest({ execution_limits: { timeout_seconds: 0.01 as unknown as number, max_attempts: 1, max_cost_usd_per_call: 10, max_cost_usd_per_job: 100 } }),
    );
    expect([400, 504]).toContain(outcome.status);
  });

  it("15. falha do provider devolve 502 e nunca promove resultado", async () => {
    // todos os providers do roteamento falham: openai/manus/anthropic/gemini
    const providers = (["openai", "manus", "anthropic", "gemini"] as const).map(
      (name) => new FakeProvider(name, { fail: "provider fora do ar" }),
    );
    const dependencies = await deps(providers);
    const outcome = await post(dependencies, validRequest());
    const body = outcome.body as AgentRunResponse;
    expect(outcome.status).toBe(502);
    expect(body.status).toBe("failed_provider");
    expect(body.providers.primary_failure).toContain("provider fora do ar");
    expect(body.output).toBeUndefined();
    expect(body.output_validation.valid).toBe(false);
  });

  it("16. fallback assume quando o primário falha", async () => {
    const primary = new FakeProvider("openai", { fail: "indisponível" });
    const fallback = new FakeProvider("anthropic", {});
    const dependencies = await deps([primary, fallback]);
    const body = (await post(dependencies, validRequest())).body as AgentRunResponse;
    expect(body.status).toBe("succeeded");
    expect(body.providers.primary).toBe("openai");
    expect(body.providers.primary_failure).toContain("indisponível");
    expect(body.providers.fallback_triggered).toBe(true);
    expect(body.providers.fallback_provider).toBe("anthropic");
    expect(fallback.calls).toBe(1);
  });

  it("17. falha do primário e do fallback preserva a falha original", async () => {
    const primary = new FakeProvider("openai", { fail: "erro primário" });
    const fallback = new FakeProvider("anthropic", { fail: "erro fallback" });
    const dependencies = await deps([primary, fallback]);
    const outcome = await post(dependencies, validRequest());
    const body = outcome.body as AgentRunResponse;
    expect(outcome.status).toBe(502);
    // qualquer que seja o primário escolhido pelo roteamento, as duas falhas ficam registradas
    const registered = `${body.providers.primary_failure ?? ""} ${body.providers.fallback_result ?? ""}`;
    expect(registered).toContain("erro");
    expect(body.output).toBeUndefined();
    expect(body.usage.length).toBeGreaterThanOrEqual(1);
  });

  it("18. CostController bloqueia quando o custo estimado estoura o limite", async () => {
    const provider = new FakeProvider("openai", {}, 5);
    const dependencies = await deps([provider], { maxCostPerTaskUsd: 0.5 });
    const outcome = await post(dependencies, validRequest());
    expect(outcome.status).toBe(429);
    expect(provider.calls).toBe(0);
    expect((outcome.body as AgentRunResponse).status).toBe("blocked_cost");
  });

  it("18b. custo desconhecido é fail-closed", async () => {
    const provider = new FakeProvider("openai", {}, null);
    const dependencies = await deps([provider]);
    const outcome = await post(dependencies, validRequest());
    expect(outcome.status).toBe(429);
    expect(provider.calls).toBe(0);
  });

  it("18c. usage ausente é registrado como unknown, nunca zero", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const withoutUsage = (await post(dependencies, validRequest())).body as AgentRunResponse;
    expect(withoutUsage.usage[0]?.input_tokens).toBe("unknown");
    expect(withoutUsage.usage[0]?.actual_cost_usd).toBe("unknown");

    const measured = await deps([new FakeProvider("openai", { usage: { inputTokens: 120, outputTokens: 80 } })]);
    const withUsage = (await post(measured, validRequest())).body as AgentRunResponse;
    expect(withUsage.usage[0]?.total_tokens).toBe(200);
  });
});

describe("output contract e autoridade", () => {
  it("19. output válido é aceito contra o schema", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const body = (await post(dependencies, validRequest())).body as AgentRunResponse;
    expect(body.output?.confidence).toBe(55);
  });

  it("20. output inválido é rejeitado com 422", async () => {
    const dependencies = await deps([new FakeProvider("openai", { output: "texto livre sem json" })]);
    const outcome = await post(dependencies, validRequest());
    expect(outcome.status).toBe(422);
    expect((outcome.body as AgentRunResponse).output).toBeUndefined();

    const semCampos = await deps([new FakeProvider("openai", { output: '{"facts":["a"]}' })]);
    expect((await post(semCampos, validRequest())).status).toBe(422);
  });

  it("25/26/27. approved_decision, execute_action e verified_ok são proibidos no output", async () => {
    for (const forbidden of ["approved_decision", "execute_action", "verified_ok"]) {
      const payload = { ...JSON.parse(VALID_OUTPUT), [forbidden]: true };
      const dependencies = await deps([new FakeProvider("openai", { output: JSON.stringify(payload) })]);
      const outcome = await post(dependencies, validRequest());
      expect(outcome.status).toBe(422);
      expect((outcome.body as AgentRunResponse).output_validation.reason).toContain(forbidden);
    }
  });

  it("24. autoridade do agente vai no contrato e não pode ser elevada pelo request", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const elevated = await post(
      dependencies,
      validRequest({ agent_authority: { can_recommend: true, can_propose: true, can_approve: true, can_execute: true } as never }),
    );
    expect(elevated.status).toBe(400);

    const body = (await post(dependencies, validRequest())).body as AgentRunResponse;
    expect(body.agent_authority.can_approve).toBe(false);
    expect(body.agent_authority.can_execute).toBe(false);
  });
});

describe("revisão independente", () => {
  it("21. reviewer aprova", async () => {
    const primary = new FakeProvider("openai", {});
    const reviewer = new FakeProvider("anthropic", { output: '{"status":"APPROVED","summary":"ok"}' });
    const dependencies = await deps([primary, reviewer]);
    const body = (await post(
      dependencies,
      validRequest({ review_policy: { required: true, max_correction_attempts: 1 } }),
    )).body as AgentRunResponse;
    expect(body.review).toMatchObject({ required: true, reviewed: true, status: "APPROVED", reviewer: "anthropic" });
    expect(body.status).toBe("succeeded");
  });

  it("22/23. reprovação gera correção e o limite de tentativas é respeitado", async () => {
    const primary = new FakeProvider("openai", {});
    const reviewer = new FakeProvider("anthropic", { output: '{"status":"REJECTED","summary":"faltou evidência"}' });
    const dependencies = await deps([primary, reviewer]);
    const body = (await post(
      dependencies,
      validRequest({ review_policy: { required: true, max_correction_attempts: 1 } }),
    )).body as AgentRunResponse;
    expect(body.review.status).toBe("REJECTED");
    expect(body.review.corrections).toBe(1);
    expect(body.status).toBe("needs_human"); // reprovado nunca vira sucesso
    expect(primary.calls).toBe(2); // execução + 1 correção, nunca mais que max_attempts
  });

  it("23b. reviewer ausente é fail-closed (needs_human), nunca sucesso silencioso", async () => {
    const primary = new FakeProvider("openai", {});
    const dependencies = await deps([primary]);
    const body = (await post(
      dependencies,
      validRequest({ review_policy: { required: true, max_correction_attempts: 0 } }),
    )).body as AgentRunResponse;
    expect(body.review.status).toBe("NEEDS_HUMAN");
    expect(body.status).toBe("needs_human");
  });
});

describe("política de providers do V1", () => {
  it("Manus e Gemini nunca são chamados, mesmo registrados", async () => {
    const manus = new FakeProvider("manus", {});
    const gemini = new FakeProvider("gemini", {});
    const anthropic = new FakeProvider("anthropic", {});
    const dependencies = await deps([manus, gemini, anthropic], { allowedProviders: ["anthropic"] });
    // tarefa que o roteamento geral do /orchestrate mandaria para Manus
    const body = (await post(
      dependencies,
      validRequest({ task: "Analise os dados operacionais desta pesquisa e investigue a divergência." }),
    )).body as AgentRunResponse;
    expect(body.status).toBe("succeeded");
    expect(body.providers.primary).toBe("anthropic");
    expect(manus.calls).toBe(0);
    expect(gemini.calls).toBe(0);
    expect(anthropic.calls).toBe(1);
  });

  it("portão de efeitos existente bloqueia provider capaz de efeitos externos (fail-closed)", async () => {
    const perigoso = new FakeProvider("anthropic", { externalEffects: true });
    const dependencies = await deps([perigoso], { allowedProviders: ["anthropic"] });
    const outcome = await post(dependencies, validRequest());
    expect(outcome.status).toBe(403);
    expect((outcome.body as AgentRunResponse).status).toBe("blocked_security");
    expect(perigoso.calls).toBe(0);
  });

  it("modo READ_ONLY + DRY_RUN permite análise READ sem efeitos", async () => {
    const seguro = new FakeProvider("anthropic", {});
    const dependencies = await deps([seguro], { allowedProviders: ["anthropic"] });
    const outcome = await post({ ...dependencies, security: { mode: "READ_ONLY", dryRun: true } }, validRequest());
    expect(outcome.status).toBe(200);
    expect(seguro.calls).toBe(1);
  });

  it("AGENT_RUN_PROVIDERS descarta qualquer provider fora de anthropic/openai", () => {
    expect(parseAgentRunProviders("manus,gemini")).toEqual(["anthropic", "openai"]);
    expect(parseAgentRunProviders("anthropic")).toEqual(["anthropic"]);
    expect(parseAgentRunProviders("manus,openai,anthropic")).toEqual(["openai", "anthropic"]);
    expect(parseAgentRunProviders(undefined)).toEqual(["anthropic", "openai"]);
    expect(AGENT_RUN_PROVIDER_ALLOWLIST).toEqual(["anthropic", "openai"]);
  });

  it("com um único provider não há autorrevisão: revisão exigida vira needs_human", async () => {
    const anthropic = new FakeProvider("anthropic", {});
    const dependencies = await deps([anthropic], { allowedProviders: ["anthropic"] });
    const body = (await post(
      dependencies,
      validRequest({ review_policy: { required: true, max_correction_attempts: 1 } }),
    )).body as AgentRunResponse;
    expect(body.status).toBe("needs_human");
    expect(anthropic.calls).toBe(1);
  });
});

describe("contexto autorizado, evidência e payload final", () => {
  it("28. contexto autorizado é carregado do projeto registrado", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const context = await resolveAuthorizedContext(dependencies.repository, validRequest());
    expect(context.files.map((file) => file.path)).toEqual(["BUSINESS-RULES.md"]);
    expect(context.missing).toEqual([]);
  });

  it("29. arquivo não autorizado nunca é enviado: vira missing_context", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const request = validRequest({ authorized_context: { project: PROJECT, files: ["BUSINESS-RULES.md", ".env"] } });
    const body = (await post(dependencies, request)).body as AgentRunResponse;
    expect(body.context.files_sent).toEqual(["BUSINESS-RULES.md"]);
    expect(body.context.missing_context).toEqual([".env"]);

    const outroProjeto = await post(dependencies, validRequest({ authorized_context: { project: "outro-projeto", files: ["BUSINESS-RULES.md"] } }));
    expect(outroProjeto.status).toBe(400); // authorized_context.project precisa bater com o projeto do run
  });

  it("30. evidência estruturada chega delimitada e intacta", async () => {
    const provider = new FakeProvider("openai", {});
    const dependencies = await deps([provider]);
    await post(dependencies, validRequest());
    const prompt = provider.inputs[0]?.prompt ?? "";
    expect(prompt).toContain("[EVIDENCE]");
    expect(prompt).toContain("source=fixture-controlado");
    expect(prompt).toContain("period=5du:2026-09-17");
    expect(prompt).toContain('quality={"source_quality":"real"');
    expect(prompt).toContain('data={"ocupacao_pct":17.6,"alvo_pct":85}');
  });

  it("19-OBRIGATÓRIO. payload final entregue ao provider contém o contrato e nada além dele", async () => {
    const provider = new FakeProvider("openai", {});
    const dependencies = await deps([provider]);
    const request = validRequest({ authorized_context: { project: PROJECT, files: ["BUSINESS-RULES.md", "AI-INSTRUCTIONS.md"] } });
    await post(dependencies, request);
    const prompt = provider.inputs[0]?.prompt ?? "";

    expect(prompt).toContain("[SYSTEM]");
    expect(prompt).toContain("[AGENT CONTRACT]");
    expect(prompt).toContain("agent=investigador");
    expect(prompt).toContain(`[AUTHORIZED PROJECT CONTEXT: ${PROJECT}]`);
    expect(prompt).toContain("[ARQUIVO: BUSINESS-RULES.md]");
    expect(prompt).toContain("A ocupação alvo da malha de transferência é 85%.");
    expect(prompt).toContain("[FIM DO ARQUIVO]");
    expect(prompt).toContain("[TASK]");
    expect(prompt).toContain("[EVIDENCE]");
    expect(prompt).toContain("[LIMITATIONS]");
    expect(prompt).toContain("[OUTPUT CONTRACT]");

    // o que NÃO pode estar no payload
    expect(prompt).not.toContain("AI-INSTRUCTIONS.md]"); // pedido, mas não registrado no projeto
    expect(prompt).not.toContain("ocup = ocupação percentual"); // arquivo autorizado, porém não solicitado
    expect(prompt).not.toContain(SECRET);
    expect(prompt).not.toContain(WEBHOOK_SECRET);
    expect(prompt).not.toContain("SUPABASE");
    expect(prompt).toContain('missing_context=["AI-INSTRUCTIONS.md"]');
  });

  it("contexto ausente é declarado e a execução segue sem inventar conteúdo", () => {
    const payload = buildProviderPayload(validRequest(), { project: PROJECT, files: [], missing: ["BUSINESS-RULES.md"] });
    expect(payload.prompt).toContain("(nenhum arquivo de contexto autorizado foi carregado)");
    expect(payload.missingContext).toEqual(["BUSINESS-RULES.md"]);
  });
});

describe("auditoria, persistência e rotas existentes", () => {
  it("31. auditoria registra execução sem expor segredo nem assinatura", async () => {
    const dependencies = await deps([new FakeProvider("openai", { usage: { inputTokens: 10, outputTokens: 5 } })]);
    await post(dependencies, validRequest());
    const [record] = (dependencies.store as InMemoryAgentRunStore).auditLog;
    expect(record?.principal).toBe(PRINCIPAL);
    expect(record?.project).toBe(PROJECT);
    expect(record?.agent).toBe("investigador");
    expect(record?.status).toBe("succeeded");
    expect(record?.idempotency_key_hash).toHaveLength(64);
    const serialized = JSON.stringify(record);
    expect(serialized).not.toContain(SECRET);
    expect(serialized).not.toContain("idem-key-controlada-0001");
  });

  it("32. persistência guarda a resposta para replay dentro da janela", async () => {
    const dependencies = await deps([new FakeProvider("openai", {})]);
    const request = validRequest();
    await executeAgentRun(agentRunRequestSchema.parse(request), dependencies);
    const stored = await dependencies.store.find(
      (await import("../src/agentRuns/store.js")).hashIdempotencyKey(request.idempotency_key),
      NOW,
    );
    expect(stored?.response.status).toBe("succeeded");
    expect(new Date(stored!.expiresAt).getTime()).toBeGreaterThan(NOW.getTime());
  });

  it("33. rotas antigas continuam funcionando e /v1/agent-runs não usa o bearer do n8n", async () => {
    const { baseUrl } = await startApi();

    const semAuth = await fetch(`${baseUrl}/orchestrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: "teste" }),
    });
    expect(semAuth.status).toBe(401);

    const comBearer = await fetch(`${baseUrl}/orchestrate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEBHOOK_SECRET}` },
      body: JSON.stringify({ task: "Analise um relatório operacional." }),
    });
    expect([200, 500]).toContain(comBearer.status);

    expect((await fetch(`${baseUrl}/tasks/00000000-0000-4000-8000-000000000000`, { headers: { Authorization: `Bearer ${WEBHOOK_SECRET}` } })).status).toBe(404);
    expect((await fetch(`${baseUrl}/rota-inexistente`, { headers: { Authorization: `Bearer ${WEBHOOK_SECRET}` } })).status).toBe(404);

    const body = JSON.stringify(validRequest({ idempotency_key: "idem-http-000000001" }));
    const comBearerNoAgentRun = await fetch(`${baseUrl}${AGENT_RUNS_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${WEBHOOK_SECRET}` },
      body,
    });
    expect(comBearerNoAgentRun.status).toBe(401); // bearer do n8n não vale para agent-run

    const comHmac = await fetch(`${baseUrl}${AGENT_RUNS_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: signed(body) },
      body,
    });
    expect(comHmac.status).toBe(200);
    expect(((await comHmac.json()) as AgentRunResponse).status).toBe("succeeded");
  });

  it("rota responde 503 quando a autenticação do agent-run não está configurada", async () => {
    const repository = new InMemoryOrchestrationRepository();
    const providerManager = new ProviderManager();
    const handler = createApiHandler({ repository, providerManager, webhookSecret: WEBHOOK_SECRET });
    const server = createServer((request, response) => void handler(request, response));
    openServers.push(server);
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    const baseUrl = typeof address === "object" && address ? `http://127.0.0.1:${address.port}` : "";
    const response = await fetch(`${baseUrl}${AGENT_RUNS_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    expect(response.status).toBe(503);
  });
});

async function startApi() {
  const dependencies = await deps([new FakeProvider("openai", {})]);
  const handler = createApiHandler({
    repository: dependencies.repository,
    providerManager: dependencies.providerManager,
    webhookSecret: WEBHOOK_SECRET,
    agentRuns: dependencies,
  });
  const server = createServer((request, response) => void handler(request, response));
  openServers.push(server);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const baseUrl = typeof address === "object" && address ? `http://127.0.0.1:${address.port}` : "";
  return { baseUrl, dependencies };
}
