import type { ProviderName, TaskResult } from "../providers/types.js";
import { resolveContext } from "./contextResolver.js";
import { classifyTask } from "./taskClassifier.js";
import { routeTask } from "./routingEngine.js";
import { planTask } from "./taskPlanner.js";
import { evaluateExecution, loadExecutionModeFromEnv, type SecurityContext } from "./securityLayer.js";
import { ProviderManager } from "./providerManager.js";
import { validateResult } from "./validationEngine.js";
import { buildEvidenceRecord, InMemoryEvidenceSink, type EvidenceSink } from "./evidenceManager.js";
import { CostController, loadCostControlConfigFromEnv } from "./costController.js";
import { Observability } from "./observability.js";
import type { EvidenceRecord, OrchestrationRequest, OrchestrationResult, StepExecutionResult } from "./types.js";

export interface OrchestrateOptions {
  security?: SecurityContext;
  projectsRoot?: string;
  providerManager?: ProviderManager;
  evidenceSink?: EvidenceSink;
  observability?: Observability;
  costController?: CostController;
}

/**
 * FASE 1-9 entrypoint: ENTENDER → CLASSIFICAR → ESCOLHER → (se o gate de
 * segurança permitir) INVESTIGAR/CONSTRUIR via ProviderManager → VALIDAR
 * via validationEngine → REGISTRAR via evidenceManager/Observability.
 *
 * Ação de escrita vs. leitura (FASE 7): usamos
 * `classification.requiresImplementation` como sinal — uma tarefa que
 * pede implementação/mudança de código é tratada como ação de escrita
 * (precisa de aprovação fora de AUTONOMOUS); investigação, decisão e
 * análise são tratadas como leitura (sempre permitidas, mesmo em
 * READ_ONLY). É uma heurística documentada, não uma garantia absoluta —
 * se um provider futuramente reportar side-effects reais (ex.: Manus
 * agindo sobre ferramentas), esse sinal deve vir do próprio `TaskResult`,
 * não só da classificação do prompt.
 */
export async function orchestrate(
  request: OrchestrationRequest,
  options: OrchestrateOptions = {},
): Promise<OrchestrationResult> {
  const security = options.security ?? loadExecutionModeFromEnv();
  const providerManager = options.providerManager ?? new ProviderManager();
  const evidenceSink = options.evidenceSink ?? new InMemoryEvidenceSink();
  const observability = options.observability ?? new Observability();
  const costController = options.costController ?? new CostController(loadCostControlConfigFromEnv());

  const context = await resolveContext(request.project, options.projectsRoot);
  const classification = classifyTask(request.task);
  const routing = routeTask(classification);
  const plan = planTask(classification, routing);

  const isWriteAction = classification.requiresImplementation;
  const gate = evaluateExecution(security, isWriteAction);

  const base: OrchestrationResult = {
    classification,
    context,
    routing,
    plan,
    executionMode: security.mode,
    dryRun: security.dryRun,
    requiresApproval: gate.requiresApproval || !gate.allowed,
    results: [],
    evidence: [],
  };

  if (!gate.allowed) {
    observability.log({ task_id: request.task, status: "skipped", error: gate.reason });
    return base;
  }

  const results: StepExecutionResult[] = [];
  const evidence: EvidenceRecord[] = [];
  let lastSuccessful: { provider: ProviderName; result: TaskResult } | undefined;

  for (const step of plan.steps) {
    const taskId = `${Date.now()}-${step.provider}`;

    if (!providerManager.has(step.provider)) {
      results.push({ provider: step.provider, purpose: step.purpose, status: "skipped", reason: "Provider não registrado no Provider Manager." });
      observability.log({ task_id: taskId, provider: step.provider, status: "skipped", error: "provider não registrado" });
      continue;
    }

    const start = performance.now();
    try {
      const result = await providerManager.call(step.provider, {
        taskId,
        prompt: request.task,
        project: request.project,
        skill: classification.skills[0],
      });
      const durationMs = performance.now() - start;

      results.push({ provider: step.provider, purpose: step.purpose, status: "success", output: result.output });
      observability.log({ task_id: taskId, provider: step.provider, status: "success", duration_ms: Math.round(durationMs) });

      const cost = costController.evaluate(undefined);
      const record = buildEvidenceRecord({
        taskId,
        project: request.project,
        provider: step.provider,
        skill: classification.skills[0],
        routingReason: routing.reason,
        result,
        confidence: routing.confidence,
        timestamp: new Date().toISOString(),
        limitations: cost.estimatedCostUsd === "unknown" ? "Custo não reportado pelo provider (unknown)." : undefined,
      });
      await evidenceSink.record(record);
      evidence.push(record);

      lastSuccessful = { provider: step.provider, result };
    } catch (error) {
      const durationMs = performance.now() - start;
      const message = error instanceof Error ? error.message : String(error);
      results.push({ provider: step.provider, purpose: step.purpose, status: "error", reason: message });
      observability.log({ task_id: taskId, provider: step.provider, status: "error", duration_ms: Math.round(durationMs), error: message });
    }
  }

  let validation: OrchestrationResult["validation"];
  if (lastSuccessful) {
    const outcome = await validateResult(
      providerManager,
      routing,
      { taskId: `${Date.now()}-review`, prompt: request.task, project: request.project, skill: classification.skills[0] },
      lastSuccessful.result,
    );
    validation = { reviewed: outcome.reviewed, reviewer: outcome.reviewer, reviewOutput: outcome.reviewResult?.output };
    if (outcome.reviewed && outcome.reviewResult) {
      const record = buildEvidenceRecord({
        taskId: `${Date.now()}-review`,
        project: request.project,
        provider: outcome.reviewer as ProviderName,
        skill: classification.skills[0],
        routingReason: `Revisão do resultado de ${lastSuccessful.provider} (FASE 9).`,
        result: outcome.reviewResult,
        confidence: routing.confidence,
        timestamp: new Date().toISOString(),
      });
      await evidenceSink.record(record);
      evidence.push(record);
    }
  }

  return { ...base, results, evidence, validation };
}

export * from "./types.js";
export { classifyTask } from "./taskClassifier.js";
export { routeTask } from "./routingEngine.js";
export { planTask } from "./taskPlanner.js";
export { resolveContext } from "./contextResolver.js";
export { ProviderManager, ProviderNotRegisteredError } from "./providerManager.js";
export { validateResult } from "./validationEngine.js";
export { buildEvidenceRecord, InMemoryEvidenceSink } from "./evidenceManager.js";
export { CostController, loadCostControlConfigFromEnv } from "./costController.js";
export { evaluateExecution, loadExecutionModeFromEnv } from "./securityLayer.js";
export { Observability, ConsoleLogSink } from "./observability.js";
