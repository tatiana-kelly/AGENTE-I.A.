import { resolveContext } from "./contextResolver.js";
import { classifyTask } from "./taskClassifier.js";
import { routeTask } from "./routingEngine.js";
import { planTask } from "./taskPlanner.js";
import { evaluateExecution, loadExecutionModeFromEnv, type SecurityContext } from "./securityLayer.js";
import type { OrchestrationRequest, OrchestrationResult } from "./types.js";

export interface OrchestrateOptions {
  security?: SecurityContext;
  projectsRoot?: string;
}

/**
 * FASE 1 CORE entrypoint: ENTENDER → CLASSIFICAR → ESCOLHER. The remaining
 * steps of the pipeline (INVESTIGAR/CONSTRUIR via ProviderManager, VALIDAR
 * via validationEngine, REGISTRAR via evidenceManager) are dependency-
 * injected by the caller once FASE 2 wires real providers in — they are not
 * called from here, so this stays fully testable without live API keys.
 */
export async function orchestrate(
  request: OrchestrationRequest,
  options: OrchestrateOptions = {},
): Promise<OrchestrationResult> {
  const security = options.security ?? loadExecutionModeFromEnv();

  const context = await resolveContext(request.project, options.projectsRoot);
  const classification = classifyTask(request.task);
  const routing = routeTask(classification);
  const plan = planTask(classification, routing);

  // Conservative default: until a concrete execution step reports it's
  // read-only, treat the plan as potentially write-capable so FASE 7's
  // approval gate applies. Callers that know a given step is read-only
  // should re-evaluate via `evaluateExecution(security, false)`.
  const gate = evaluateExecution(security, true);

  return {
    classification,
    context,
    routing,
    plan,
    executionMode: security.mode,
    dryRun: security.dryRun,
    requiresApproval: gate.requiresApproval || !gate.allowed,
  };
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
