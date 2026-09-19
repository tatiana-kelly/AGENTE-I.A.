/**
 * Execução de um agent-run: idempotência → contexto → payload → provider (com fallback) →
 * revisão independente → validação do output. Tudo reutilizando o pipeline já existente:
 * classifyTask/routeTask, ProviderManager, CostController e runReviewCycle.
 *
 * Não existe segundo CostController, segundo fallback nem segundo reviewer. Falha em qualquer etapa
 * é fail-closed: nenhum texto arbitrário vira sucesso.
 */

import { randomUUID } from "node:crypto";
import type { CostController } from "../orchestrator/costController.js";
import type { ProviderManager } from "../orchestrator/providerManager.js";
import { classifyTask } from "../orchestrator/taskClassifier.js";
import { routeTask } from "../orchestrator/routingEngine.js";
import { evaluateExecution, loadExecutionModeFromEnv, type SecurityContext } from "../orchestrator/securityLayer.js";
import { runReviewCycle } from "../orchestrator/validationEngine.js";
import type { OrchestrationRepository, ProjectPrincipalType } from "../persistence/index.js";
import { canAccessProject } from "../projects/access.js";
import { ProviderCallError } from "../providers/callError.js";
import { ProviderHttpError } from "../providers/httpClient.js";
import type { ProviderName, TaskInput, TaskResult } from "../providers/types.js";
import type { AgentRunRequest, AgentRunResponse, AgentRunStatus, AgentRunUsage, CallOutcome } from "./contract.js";
import { PROTOCOL_VERSION, forbiddenAuthorityFields, investigationOutputSchema } from "./contract.js";
import { buildProviderPayload, resolveAgentDefinition, resolveAuthorizedContext } from "./payload.js";
import type { AgentRunStore } from "./store.js";
import { expiryFrom, hashIdempotencyKey, hashRequest } from "./store.js";

export interface AgentRunDependencies {
  repository: OrchestrationRepository;
  providerManager: ProviderManager;
  store: AgentRunStore;
  costController: CostController;
  clock?: () => Date;
  /** Providers permitidos, em ordem de preferência. Padrão: anthropic, openai. */
  allowedProviders?: readonly ProviderName[];
  /** Portão de efeitos existente (securityLayer). Padrão: ORCHESTRATOR_MODE/DRY_RUN do ambiente. */
  security?: SecurityContext;
  /**
   * Teto de custo por chamada ESPECÍFICO do agent-run (sobrepõe o estimatedMaxCostUsd do provider).
   * Permite habilitar um provider no agent-run sem habilitá-lo no /orchestrate.
   */
  providerCostCaps?: Partial<Record<ProviderName, number>>;
  /** Limite de tokens de saída por provider ESPECÍFICO do agent-run (não altera o /orchestrate). */
  providerMaxOutputTokens?: Partial<Record<ProviderName, number>>;
}

/** V1 aprovado: somente Anthropic e OpenAI. */
export const AGENT_RUN_PROVIDER_ALLOWLIST: readonly ProviderName[] = ["anthropic", "openai"];
export const DEFAULT_AGENT_RUN_PROVIDERS: readonly ProviderName[] = AGENT_RUN_PROVIDER_ALLOWLIST;

/** Lê AGENT_RUN_PROVIDERS ("anthropic,openai"); qualquer valor fora da allowlist do V1 é descartado. */
export function parseAgentRunProviders(raw: string | undefined): ProviderName[] {
  const requested = (raw ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter((item): item is ProviderName => (AGENT_RUN_PROVIDER_ALLOWLIST as readonly string[]).includes(item));
  return requested.length > 0 ? [...new Set(requested)] : [...DEFAULT_AGENT_RUN_PROVIDERS];
}

export interface AgentRunOutcome {
  status: number;
  body: AgentRunResponse | { error: string; detail?: string };
}

const STATUS_CODE: Record<AgentRunStatus, number> = {
  succeeded: 200,
  needs_human: 200,
  rejected_output: 422,
  blocked_cost: 429,
  blocked_security: 403,
  failed_provider: 502,
  timeout: 504,
};

class TimeoutError extends Error {}

type CallGate =
  | { allowed: true; estimate: number }
  | { allowed: false; kind: "security" | "cost" | "unregistered"; reason: string };

/** O que o revisor independente deve verificar. Ele revisa; não decide, não aprova, não executa. */
const REVIEW_CHECKLIST = [
  "[REVIEW CHECKLIST]",
  "Você é o REVISOR INDEPENDENTE desta investigação. Verifique, contra o contexto autorizado e as evidências acima:",
  "1. FATOS: cada fato está sustentado por uma evidência recebida e citada pelo id?",
  "2. CÁLCULOS: estão corretos e só usam dados fornecidos?",
  "3. INFERÊNCIAS e HIPÓTESES: estão separadas dos fatos e não tratam correlação como causa?",
  "4. CONTRADIÇÕES: as contradições relevantes foram declaradas?",
  "5. DADOS AUSENTES: o que falta foi declarado, sem inventar dados?",
  "6. CONFIANÇA: é compatível com a qualidade e a completude das evidências?",
  "7. AUTORIDADE: o resultado não aprova decisão, não executa ação e não declara resultado verificado?",
  "Se houver erro, responda REJECTED e diga exatamente o que corrigir. Você NÃO aprova decisão empresarial,",
  "NÃO executa ação e NÃO declara verified_ok: APPROVED significa apenas que a investigação está correta.",
  "[/REVIEW CHECKLIST]",
].join("\n");

/** "service:sal-intelligence-os" → { type: "service", id: "sal-intelligence-os" } */
function parsePrincipal(value: string): { type: ProjectPrincipalType; id: string } | undefined {
  const separator = value.indexOf(":");
  if (separator <= 0) return undefined;
  const type = value.slice(0, separator);
  const id = value.slice(separator + 1).trim();
  if (!id) return undefined;
  if (type !== "user" && type !== "service" && type !== "agent") return undefined;
  return { type, id };
}

async function withTimeout<T>(promise: Promise<T>, seconds: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new TimeoutError(`Tempo limite de ${seconds}s excedido.`)), seconds * 1000);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

interface CallObservation {
  outcome: CallOutcome;
  model?: string;
  usage?: { inputTokens: number; outputTokens: number };
  attempts?: number;
  reason?: string;
}

/**
 * Traduz o desfecho de uma chamada em observação de uso. Truncamento/incompletude preservam os tokens que o
 * provider informou (ProviderCallError); timeout e rejeição não têm tokens — ficam como
 * usage_status=unavailable_from_provider, mas a tentativa continua registrada.
 */
function observe(call: TaskResult | undefined, error: unknown): CallObservation {
  if (call) return { outcome: "success", model: call.model, usage: call.usage, attempts: call.attempts ?? 1 };
  const reason = (error instanceof Error ? error.message : String(error)).slice(0, 500);
  if (error instanceof ProviderCallError) {
    return { outcome: error.kind, model: error.model, usage: error.usage, attempts: error.attempts, reason };
  }
  if (error instanceof TimeoutError || (error instanceof Error && error.name === "AbortError")) {
    return { outcome: "timeout", attempts: 1, reason };
  }
  if (error instanceof ProviderHttpError) {
    return { outcome: error.status >= 500 ? "provider_error" : "rejected", attempts: 1, reason };
  }
  return { outcome: "transport_error", reason };
}

function parseOutput(raw: string): { ok: true; value: unknown } | { ok: false; reason: string } {
  const json = raw.match(/\{[\s\S]*\}/)?.[0];
  if (!json) return { ok: false, reason: "Resposta não contém JSON." };
  try {
    return { ok: true, value: JSON.parse(json) };
  } catch {
    return { ok: false, reason: "JSON inválido na resposta do provider." };
  }
}

export async function executeAgentRun(
  request: AgentRunRequest,
  dependencies: AgentRunDependencies,
): Promise<AgentRunOutcome> {
  const now = dependencies.clock?.() ?? new Date();
  const keyHash = hashIdempotencyKey(request.idempotency_key);
  const requestHash = hashRequest(request);

  const stored = await dependencies.store.find(keyHash, now);
  if (stored) {
    if (stored.requestHash !== requestHash) {
      return {
        status: 409,
        body: { error: "idempotency_conflict", detail: "idempotency_key já usada com um corpo diferente." },
      };
    }
    return { status: STATUS_CODE[stored.response.status], body: { ...stored.response, replayed: true } };
  }

  // Permissão de projeto: o principal precisa de agent_run (ou admin) NAQUELE projeto. Fail-closed.
  const principal = parsePrincipal(request.principal);
  if (!principal) {
    return { status: 403, body: { error: "principal_invalid", detail: "principal deve ser <user|service|agent>:<id>." } };
  }
  const permitted = await canAccessProject(dependencies.repository, request.project, principal, "agent_run");
  if (!permitted) {
    return {
      status: 403,
      body: {
        error: "permission_denied",
        detail: `Principal sem capability agent_run no projeto ${request.project}.`,
      },
    };
  }

  const context = await resolveAuthorizedContext(dependencies.repository, request);
  // Definição do agente: vinculada ao agente do request, do registro do projeto, com sha256 (Fase 5F).
  // Na revisão consolidada não há autor, logo não há definição de agente a enviar.
  const agentDefinition = request.review_target ? undefined : await resolveAgentDefinition(dependencies.repository, request);
  const payload = buildProviderPayload(request, context, agentDefinition);
  // Decisão aprovada do V1: agent-run usa só Anthropic e OpenAI. Manus e Gemini nunca entram,
  // mesmo que o roteamento geral do /orchestrate os escolha. A ordem vem de AGENT_RUN_PROVIDERS.
  const allowed = dependencies.allowedProviders ?? DEFAULT_AGENT_RUN_PROVIDERS;
  const candidates = [...new Set(allowed)].slice(0, 2);
  const classification = routeTask(classifyTask(request.task));
  const routing = {
    ...classification,
    primary: candidates[0]!,
    fallback: candidates[1],
    // Revisor = outro provider permitido. Com um só provider não há revisor independente:
    // se a revisão for exigida, o ciclo existente falha fechado (NEEDS_HUMAN).
    reviewer: request.review_target
      ? candidates.find((provider) => !(request.review_target!.author_providers as readonly string[]).includes(provider))
      : candidates[1],
    reason: `agent-run V1: providers permitidos em ordem ${candidates.join(" → ")}`,
  };

  const usage: AgentRunUsage[] = [];
  const providers: AgentRunResponse["providers"] = { primary: routing.primary, fallback_triggered: false };
  const security = dependencies.security ?? loadExecutionModeFromEnv();
  const limits = request.execution_limits;
  let reservedCostUsd = 0;
  let attempt = 0; // chamadas do AUTOR (execução + correções) — limitadas por max_attempts
  let result: TaskResult | undefined;
  let usedProvider: ProviderName | undefined;
  let status: AgentRunStatus = "failed_provider";
  let failureDetail = "Nenhum provider executou a tarefa.";

  const taskInput: TaskInput = {
    taskId: request.request_id,
    prompt: payload.prompt,
    project: request.project,
    context: { agent: request.agent, agent_version: request.agent_version },
    modelProfile: request.profile,
    // o prazo do contrato chega ao cliente HTTP do provider (sem isto valeria o padrão de 30 s do httpClient)
    timeoutMs: request.execution_limits.timeout_seconds * 1000,
    // nenhuma retentativa automática do httpClient: cada tentativa cobrável passa pelo portão e é registrada
    maxHttpAttempts: 1,
  };

  /** Aplica o limite de saída do agent-run para aquele provider, quando configurado. */
  const withOutputLimit = (provider: ProviderName, input: TaskInput): TaskInput => {
    const limit = dependencies.providerMaxOutputTokens?.[provider];
    return limit === undefined ? input : { ...input, maxOutputTokens: limit };
  };

  /**
   * Portão ÚNICO para qualquer chamada (autor, revisor ou correção): allowlist do V1, portão de efeitos
   * existente (evaluateExecution), CostController existente e limites da requisição. Nenhuma chamada o evita.
   */
  const gateCall = (provider: ProviderName): CallGate => {
    if (!allowed.includes(provider)) {
      return { allowed: false, kind: "security", reason: `Provider ${provider} fora da allowlist do agent-run.` };
    }
    if (!dependencies.providerManager.has(provider)) {
      return { allowed: false, kind: "unregistered", reason: `Provider ${provider} não registrado.` };
    }
    const capabilities = dependencies.providerManager.capabilities(provider);
    const effect = evaluateExecution(security, "READ", capabilities.mayProduceExternalEffects);
    if (!effect.allowed) return { allowed: false, kind: "security", reason: effect.reason };
    const estimate = dependencies.providerCostCaps?.[provider] ?? capabilities.estimatedMaxCostUsd;
    const projected = estimate === undefined ? undefined : reservedCostUsd + estimate;
    // O orçamento do job é a aprovação explícita da requisição autenticada (sal.agent-run/1.0).
    const evaluation = dependencies.costController.evaluate(projected, limits.max_cost_usd_per_job);
    if (estimate !== undefined && estimate > limits.max_cost_usd_per_call) {
      return { allowed: false, kind: "cost", reason: `Custo estimado por chamada acima de US$ ${limits.max_cost_usd_per_call}.` };
    }
    if (projected !== undefined && projected > limits.max_cost_usd_per_job) {
      return { allowed: false, kind: "cost", reason: `Custo acumulado acima de US$ ${limits.max_cost_usd_per_job}.` };
    }
    if (!evaluation.withinBudget || evaluation.requiresConfirmation) {
      return { allowed: false, kind: "cost", reason: evaluation.reason };
    }
    return { allowed: true, estimate: estimate as number };
  };

  const record = (
    role: AgentRunUsage["role"],
    provider: ProviderName,
    observation: CallObservation,
    estimate: number,
    callAttempt: number,
    startedAt: number,
  ): void => {
    const reported = observation.usage !== undefined;
    usage.push({
      role,
      provider,
      outcome: observation.outcome,
      usage_status: reported ? "reported" : "unavailable_from_provider",
      provider_attempts: observation.attempts ?? "unknown",
      ...(observation.reason ? { failure_reason: observation.reason } : {}),
      model: observation.model ?? "unknown",
      input_tokens: observation.usage?.inputTokens ?? "unknown",
      output_tokens: observation.usage?.outputTokens ?? "unknown",
      total_tokens: observation.usage ? observation.usage.inputTokens + observation.usage.outputTokens : "unknown",
      estimated_cost_usd: estimate,
      reserved_cost_usd: Math.round(reservedCostUsd * 1e6) / 1e6, // soma de tetos; sem ruído de ponto flutuante
      actual_cost_usd: "unknown", // nenhum provider devolve custo real hoje — nunca inventar, nunca virar zero
      attempt: callAttempt,
      latency_ms: Date.now() - startedAt,
    });
  };

  if (request.review_target) {
    // Revisão consolidada: o artefato já existe (consolidação determinística do SAL OS). Nenhum autor de IA.
    result = { output: JSON.stringify(request.review_target.output), sources: [], evidence: [], model: "consolidation" };
    usedProvider = request.review_target.author_providers[0];
  }

  for (const candidate of request.review_target ? [] : candidates) {
    if (attempt >= limits.max_attempts) break;
    const gate = gateCall(candidate);
    if (!gate.allowed) {
      if (gate.kind === "security") status = "blocked_security";
      else if (gate.kind === "cost") status = "blocked_cost";
      failureDetail = gate.reason;
      if (candidate === routing.primary) providers.primary_failure = failureDetail;
      continue;
    }

    attempt += 1;
    reservedCostUsd += gate.estimate; // reserva ANTES da chamada; mantida mesmo em falha (conservador)
    const startedAt = Date.now();
    try {
      const call = await withTimeout(
        dependencies.providerManager.call(candidate, withOutputLimit(candidate, taskInput)),
        limits.timeout_seconds,
      );
      record("author", candidate, observe(call, undefined), gate.estimate, attempt, startedAt);
      result = call;
      usedProvider = candidate;
      if (candidate !== routing.primary) {
        providers.fallback_triggered = true;
        providers.fallback_provider = candidate;
        providers.fallback_result = "success";
      }
      break;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const observation = observe(undefined, error);
      record("author", candidate, observation, gate.estimate, attempt, startedAt);
      failureDetail = message;
      status = observation.outcome === "timeout" ? "timeout" : "failed_provider";
      if (candidate === routing.primary) providers.primary_failure = message;
      else {
        providers.fallback_triggered = true;
        providers.fallback_provider = candidate;
        providers.fallback_result = `error: ${message}`;
      }
    }
  }

  const createdAt = now.toISOString();
  const runId = randomUUID();
  const baseResponse: AgentRunResponse = {
    protocol_version: PROTOCOL_VERSION,
    request_id: request.request_id,
    run_id: runId,
    status,
    agent: request.agent,
    agent_version: request.agent_version,
    agent_authority: request.agent_authority,
    output_validation: { valid: false, reason: failureDetail },
    review: { required: request.review_policy.required, reviewed: false, status: "NOT_RUN", corrections: 0 },
    providers,
    usage,
    context: {
      project: context.project,
      files_sent: payload.filesSent,
      missing_context: payload.missingContext,
      agent_definition: agentDefinition
        ? { path: agentDefinition.path, status: agentDefinition.status, sha256: agentDefinition.sha256 }
        : { path: "n/a", status: "not_applicable" },
    },
    mode: request.review_target ? "consolidated_review" : "investigation",
    evidence_received: request.evidence.map((item) => item.id),
    replayed: false,
    created_at: createdAt,
  };

  const finish = async (response: AgentRunResponse): Promise<AgentRunOutcome> => {
    await dependencies.store.save({
      idempotencyKeyHash: keyHash,
      requestHash,
      response,
      createdAt,
      expiresAt: expiryFrom(now),
    });
    // Auditoria consistente: provider/modelo/tentativa são do AUTOR (a última chamada de autoria), nunca do
    // revisor; tokens e latência são o TOTAL do job. Qualquer métrica ausente em alguma chamada torna o total
    // "unknown" — somar só as conhecidas subestimaria o job. O detalhe por chamada fica em response.usage.
    const authored = response.usage.filter((item) => item.role !== "reviewer");
    const lastAuthor = authored.at(-1);
    const total = (pick: (item: AgentRunUsage) => number | "unknown"): number | "unknown" =>
      response.usage.length === 0 || response.usage.some((item) => pick(item) === "unknown")
        ? "unknown"
        : response.usage.reduce((sum, item) => sum + (pick(item) as number), 0);
    await dependencies.store.audit({
      request_id: response.request_id,
      idempotency_key_hash: keyHash,
      principal: request.principal,
      project: request.project,
      agent: request.agent,
      agent_version: request.agent_version,
      provider: lastAuthor?.provider ?? usedProvider ?? "unknown",
      model: lastAuthor?.model ?? "unknown",
      attempt: lastAuthor?.attempt ?? 0,
      status: response.status,
      latency_ms: total((item) => item.latency_ms),
      input_tokens: total((item) => item.input_tokens),
      output_tokens: total((item) => item.output_tokens),
      cost_usd: total((item) => item.actual_cost_usd),
      fallback_triggered: response.providers.fallback_triggered,
      review_status: response.review.status,
      validation_status: response.output_validation.valid ? "valid" : "invalid",
      created_at: createdAt,
    });
    return { status: STATUS_CODE[response.status], body: response };
  };

  if (!result || !usedProvider) {
    return finish(baseResponse);
  }

  // Revisão independente: reutiliza o ciclo existente (revisor ≠ autor, correção limitada, fail-closed).
  // O revisor recebe o payload completo (contexto autorizado + evidências + contrato) e a lista de verificação.
  let review = baseResponse.review;
  let finalResult = result;
  if (request.review_policy.required) {
    const author = usedProvider;
    const reviewInput: TaskInput = { ...taskInput, prompt: `${payload.prompt}\n\n${REVIEW_CHECKLIST}` };
    const reviewerOutputs: string[] = [];
    let reviewerCalls = 0;
    let pendingReviewerEstimate = 0;

    // Wrapper que só registra uso e aplica timeout — as chamadas continuam indo ao ProviderManager existente.
    const recordingManager = {
      has: (name: ProviderName) => dependencies.providerManager.has(name),
      capabilities: (name: ProviderName) => dependencies.providerManager.capabilities(name),
      call: async (name: ProviderName, input: TaskInput) => {
        reviewerCalls += 1;
        const startedAt = Date.now();
        try {
          // o ciclo de revisão monta o input do revisor sem prazo; o wrapper injeta o prazo do contrato
          // o ciclo de revisão monta o input do revisor sem os campos do agent-run: o wrapper injeta prazo,
          // limite de saída e a proibição de retentativas ocultas (maxHttpAttempts=1)
          const timed = withOutputLimit(name, { ...input, timeoutMs: limits.timeout_seconds * 1000, maxHttpAttempts: 1 });
          const call = await withTimeout(dependencies.providerManager.call(name, timed), limits.timeout_seconds);
          record("reviewer", name, observe(call, undefined), pendingReviewerEstimate, reviewerCalls, startedAt);
          reviewerOutputs.push(call.output);
          return call;
        } catch (error) {
          record("reviewer", name, observe(undefined, error), pendingReviewerEstimate, reviewerCalls, startedAt);
          throw error;
        }
      },
    } as unknown as ProviderManager;

    const outcome = await runReviewCycle(recordingManager, routing, reviewInput, result, {
      artifactProvider: author,
      maxCorrectionAttempts: request.review_policy.max_correction_attempts,
      authorizeReviewer: (reviewer) => {
        const gate = gateCall(reviewer);
        if (!gate.allowed) return { allowed: false, reason: `Revisor bloqueado: ${gate.reason}` };
        pendingReviewerEstimate = gate.estimate;
        return { allowed: true, reason: "ok" };
      },
      onReviewerCallStart: async () => {
        reservedCostUsd += pendingReviewerEstimate;
      },
      requestCorrection: async (correctionPrompt) => {
        if (attempt >= limits.max_attempts) return undefined;
        const gate = gateCall(author);
        if (!gate.allowed) return undefined;
        attempt += 1;
        reservedCostUsd += gate.estimate;
        const startedAt = Date.now();
        try {
          const corrected = await withTimeout(
            dependencies.providerManager.call(author, withOutputLimit(author, { ...taskInput, prompt: correctionPrompt })),
            limits.timeout_seconds,
          );
          record("correction", author, observe(corrected, undefined), gate.estimate, attempt, startedAt);
          return corrected;
        } catch (error) {
          record("correction", author, observe(undefined, error), gate.estimate, attempt, startedAt);
          return undefined;
        }
      },
    });
    finalResult = outcome.finalResult;

    // O revisor também não tem autoridade: se tentar aprovar decisão, executar ação ou declarar
    // resultado verificado, a revisão é anulada e o caso vai para humano.
    const reviewerViolations = [
      ...new Set(
        reviewerOutputs.flatMap((output) => {
          const parsedReview = parseOutput(output);
          return parsedReview.ok ? forbiddenAuthorityFields(parsedReview.value) : [];
        }),
      ),
    ];
    const violated = reviewerViolations.length > 0;
    review = {
      required: true,
      reviewed: outcome.reviewed,
      status: violated ? "NEEDS_HUMAN" : outcome.status,
      reviewer: outcome.reviewer,
      corrections: outcome.corrections.length,
      // motivo de cada reprovação do revisor: rastreável na resposta guardada, sem depender de log
      rejections: outcome.corrections.map((item) => item.rejectionSummary),
      summary: violated
        ? `Revisor tentou exercer autoridade do SAL OS: ${reviewerViolations.join(", ")}.`
        : outcome.summary,
      authority_violation: violated,
    };
  }

  const parsed = parseOutput(finalResult.output);
  if (!parsed.ok) {
    return finish({ ...baseResponse, status: "rejected_output", review, output_validation: { valid: false, reason: parsed.reason } });
  }
  const forbidden = forbiddenAuthorityFields(parsed.value);
  if (forbidden.length > 0) {
    return finish({
      ...baseResponse,
      status: "rejected_output",
      review,
      output_validation: {
        valid: false,
        reason: `Output tentou exercer autoridade do SAL OS: ${forbidden.join(", ")}.`,
      },
    });
  }
  const validated = investigationOutputSchema.safeParse(parsed.value);
  if (!validated.success) {
    return finish({
      ...baseResponse,
      status: "rejected_output",
      review,
      // caminho do campo incluído: sem ele, a rejeição real da Fase 5G não dizia QUAL campo falhou
      output_validation: {
        valid: false,
        reason: `Output fora do contrato: ${validated.error.issues
          .slice(0, 3)
          .map((issue) => `${issue.path.join(".") || "(raiz)"}: ${issue.message}`)
          .join("; ")}.`,
      },
    });
  }

  // recomendar exige autorização explícita do request; sem ela, a saída tenta exercer autoridade que não tem
  if (!request.agent_authority.can_recommend && (validated.data.recommended_actions?.length ?? 0) > 0) {
    return finish({
      ...baseResponse,
      status: "rejected_output",
      review,
      output_validation: { valid: false, reason: "Output trouxe recommended_actions sem agent_authority.can_recommend." },
    });
  }

  const finalStatus: AgentRunStatus =
    request.review_policy.required && review.status !== "APPROVED" ? "needs_human" : "succeeded";
  return finish({
    ...baseResponse,
    status: finalStatus,
    review,
    output: validated.data,
    output_validation: { valid: true, reason: "Output validado contra sal.investigation-output/1.0." },
  });
}
