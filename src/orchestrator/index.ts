import { randomUUID } from "node:crypto";
import type { ProviderName, TaskResult } from "../providers/types.js";
import {
  buildSupabaseRepositoryFromEnv,
  type OrchestrationRepository,
  type PersistedApproval,
} from "../persistence/index.js";
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
  repository?: OrchestrationRepository;
  continuedFromTaskId?: string;
  approval?: PersistedApproval;
  approvedMaxCostUsd?: number;
  observability?: Observability;
  costController?: CostController;
}

/**
 * FASE 1-9 entrypoint: ENTENDER → CLASSIFICAR → ESCOLHER → (se o gate de
 * segurança permitir) INVESTIGAR/CONSTRUIR via ProviderManager → VALIDAR
 * via validationEngine → REGISTRAR via evidenceManager/Observability.
 *
 * Efeitos de execução (FASE 7): a classificação separa READ, WRITE,
 * EXTERNAL_ACTION e UNKNOWN. Somente READ passa em READ_ONLY; UNKNOWN é
 * bloqueado por padrão. O gate roda antes de qualquer provider.
 */
export async function orchestrate(
  request: OrchestrationRequest,
  options: OrchestrateOptions = {},
): Promise<OrchestrationResult> {
  const security = options.security ?? loadExecutionModeFromEnv();
  const providerManager = options.providerManager ?? new ProviderManager();
  const repository = options.repository ?? buildSupabaseRepositoryFromEnv();
  const evidenceSink = combineEvidenceSinks(repository, options.evidenceSink);
  const observability = options.observability ?? new Observability();
  const costController = options.costController ?? new CostController(loadCostControlConfigFromEnv());

  const context = await resolveContext(request.project, options.projectsRoot);
  const classification = classifyTask(request.task);
  const routing = routeTask(classification);
  const plan = planTask(classification, routing);
  const results: StepExecutionResult[] = [];
  const evidence: EvidenceRecord[] = [];
  const taskId = randomUUID();

  const gate = evaluateExecution(security, classification.effectLevel);

  const base: OrchestrationResult = {
    taskId,
    classification,
    context,
    routing,
    plan,
    executionMode: security.mode,
    dryRun: security.dryRun,
    requiresApproval: gate.requiresApproval || !gate.allowed,
    results,
    evidence,
  };

  const createdAt = new Date().toISOString();
  await repository?.createTask({
    id: taskId,
    request,
    continuedFromTaskId: options.continuedFromTaskId,
    approval: options.approval,
    status: "received",
    classification,
    routing,
    plan,
    executionMode: security.mode,
    dryRun: security.dryRun,
    requiresApproval: base.requiresApproval,
    createdAt,
    updatedAt: createdAt,
  });

  const recordNonSuccess = async (
    runId: string,
    provider: ProviderName,
    status: "error" | "skipped" | "blocked",
    reason: string,
  ): Promise<void> => {
    const record = buildEvidenceRecord({
      taskId,
      runId,
      project: request.project,
      provider,
      skill: classification.skills[0],
      routingReason: routing.reason,
      result: { output: "", sources: [], evidence: [] },
      status,
      reason,
      confidence: routing.confidence,
      timestamp: new Date().toISOString(),
    });
    await evidenceSink.record(record);
    evidence.push(record);
  };

  if (!gate.allowed) {
    observability.log({ task_id: request.task, status: "skipped", error: gate.reason });
    const runId = randomUUID();
    const now = new Date().toISOString();
    await repository?.createRun({
      id: runId,
      taskId,
      stepIndex: 0,
      provider: routing.primary,
      purpose: plan.steps[0]?.purpose ?? "Gate de segurança",
      status: "blocked",
      reason: gate.reason,
      startedAt: now,
      completedAt: now,
    });
    await recordNonSuccess(runId, routing.primary, "blocked", gate.reason);
    await repository?.updateTask(taskId, {
      status: gate.requiresApproval ? "awaiting_approval" : "blocked",
      requiresApproval: base.requiresApproval,
      updatedAt: new Date().toISOString(),
    });
    return base;
  }

  await repository?.updateTask(taskId, {
    status: "running",
    requiresApproval: base.requiresApproval,
    updatedAt: new Date().toISOString(),
  });

  let lastSuccessful: { provider: ProviderName; result: TaskResult } | undefined;
  let planCompleted = true;
  let reservedCostUsd = 0;

  for (const [stepIndex, step] of plan.steps.entries()) {
    const candidates = providerCandidates(step.provider, routing.primary, routing.fallback);
    const failedReasons: string[] = [];
    let stepCompleted = false;

    for (const candidate of candidates) {
      const runId = randomUUID();
      const fallbackFor = candidate === step.provider ? undefined : step.provider;

      if (!providerManager.has(candidate)) {
        const reason = "Provider não registrado no Provider Manager.";
        results.push({ provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason });
        observability.log({ task_id: runId, provider: candidate, status: "skipped", error: reason });
        await persistFinishedRun(repository, { runId, taskId, stepIndex, provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason });
        await recordNonSuccess(runId, candidate, "skipped", reason);
        failedReasons.push(`${candidate}: ${reason}`);
        continue;
      }

      const capabilities = providerManager.capabilities(candidate);
      const providerGate = evaluateExecution(
        security,
        classification.effectLevel,
        capabilities.mayProduceExternalEffects,
      );
      if (!providerGate.allowed) {
        results.push({ provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason: providerGate.reason });
        observability.log({ task_id: runId, provider: candidate, status: "skipped", error: providerGate.reason });
        await persistFinishedRun(repository, { runId, taskId, stepIndex, provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason: providerGate.reason });
        await recordNonSuccess(runId, candidate, "skipped", providerGate.reason);
        base.requiresApproval ||= providerGate.requiresApproval;
        failedReasons.push(`${candidate}: ${providerGate.reason}`);
        continue;
      }

      const estimatedTaskCost =
        capabilities.estimatedMaxCostUsd === undefined
          ? undefined
          : reservedCostUsd + capabilities.estimatedMaxCostUsd;
      const cost = costController.evaluate(estimatedTaskCost, options.approvedMaxCostUsd);
      if (!cost.withinBudget || cost.requiresConfirmation) {
        results.push({ provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason: cost.reason });
        observability.log({ task_id: runId, provider: candidate, status: "skipped", error: cost.reason });
        await persistFinishedRun(repository, { runId, taskId, stepIndex, provider: candidate, fallbackFor, purpose: step.purpose, status: "skipped", reason: cost.reason });
        await recordNonSuccess(runId, candidate, "skipped", cost.reason);
        base.requiresApproval = true;
        failedReasons.push(`${candidate}: ${cost.reason}`);
        continue;
      }
      reservedCostUsd = estimatedTaskCost as number;

      const runStartedAt = new Date().toISOString();
      await repository?.createRun({
        id: runId,
        taskId,
        stepIndex,
        provider: candidate,
        fallbackFor,
        purpose: step.purpose,
        status: "running",
        startedAt: runStartedAt,
      });
      const start = performance.now();
      let result: TaskResult;
      try {
        result = await providerManager.call(candidate, {
          taskId: runId,
          prompt: buildStepPrompt(request.task, step.purpose, context.loaded, results),
          project: request.project,
          context: {
            projectFiles: context.loaded,
            previousResults: successfulOutputs(results),
          },
          skill: classification.skills[0],
        });
      } catch (error) {
        const durationMs = performance.now() - start;
        const message = error instanceof Error ? error.message : String(error);
        results.push({ provider: candidate, fallbackFor, purpose: step.purpose, status: "error", reason: message });
        observability.log({ task_id: runId, provider: candidate, status: "error", duration_ms: Math.round(durationMs), error: message });
        await repository?.updateRun(runId, {
          status: "error",
          reason: message,
          completedAt: new Date().toISOString(),
        });
        await recordNonSuccess(runId, candidate, "error", message);
        failedReasons.push(`${candidate}: ${message}`);
        if (requiresExplicitApproval(error)) {
          base.requiresApproval = true;
          break;
        }
        continue;
      }

      const durationMs = performance.now() - start;
      results.push({ provider: candidate, fallbackFor, purpose: step.purpose, status: "success", output: result.output });
      observability.log({ task_id: runId, provider: candidate, status: "success", duration_ms: Math.round(durationMs) });
      await repository?.updateRun(runId, {
        status: "success",
        output: result.output,
        completedAt: new Date().toISOString(),
      });

      const record = buildEvidenceRecord({
        taskId,
        runId,
        project: request.project,
        provider: candidate,
        skill: classification.skills[0],
        routingReason: routing.reason,
        result,
        confidence: routing.confidence,
        timestamp: new Date().toISOString(),
        limitations: `Custo máximo reservado acumulado: US$ ${reservedCostUsd.toFixed(2)}.`,
        fallbackTriggered: fallbackFor !== undefined,
        fallbackReason: fallbackFor === undefined ? undefined : failedReasons.join(" | "),
      });
      await evidenceSink.record(record);
      evidence.push(record);

      lastSuccessful = { provider: candidate, result };
      stepCompleted = true;
      break;
    }

    if (!stepCompleted) {
      planCompleted = false;
      break;
    }
  }

  let validation: OrchestrationResult["validation"];
  if (lastSuccessful && planCompleted) {
    const reviewRunId = randomUUID();
    let reviewStarted = false;
    const outcome = await validateResult(
      providerManager,
      routing,
      {
        taskId: reviewRunId,
        prompt: request.task,
        project: request.project,
        context: { projectFiles: context.loaded, previousResults: successfulOutputs(results) },
        skill: classification.skills[0],
      },
      lastSuccessful.result,
      {
        artifactProvider: lastSuccessful.provider,
        onReviewerCallStart: async (reviewer) => {
          reviewStarted = true;
          await repository?.createRun({
            id: reviewRunId,
            taskId,
            stepIndex: plan.steps.length,
            provider: reviewer,
            purpose: `Revisão do resultado de ${lastSuccessful.provider}`,
            status: "running",
            startedAt: new Date().toISOString(),
          });
        },
        authorizeReviewer: (reviewer) => {
          const capabilities = providerManager.capabilities(reviewer);
          const reviewerGate = evaluateExecution(
            security,
            "READ",
            capabilities.mayProduceExternalEffects,
          );
          if (!reviewerGate.allowed) {
            return { allowed: false, reason: reviewerGate.reason };
          }
          const estimatedTaskCost =
            capabilities.estimatedMaxCostUsd === undefined
              ? undefined
              : reservedCostUsd + capabilities.estimatedMaxCostUsd;
          const cost = costController.evaluate(estimatedTaskCost, options.approvedMaxCostUsd);
          if (!cost.withinBudget || cost.requiresConfirmation) {
            return { allowed: false, reason: cost.reason };
          }
          reservedCostUsd = estimatedTaskCost as number;
          return { allowed: true, reason: cost.reason };
        },
      },
    );
    validation = {
      reviewed: outcome.reviewed,
      status: outcome.status,
      reviewer: outcome.reviewer,
      summary: outcome.summary,
      reviewOutput: outcome.reviewResult?.output,
    };
    base.requiresApproval ||= outcome.status === "NEEDS_HUMAN" || outcome.status === "REJECTED";
    if (outcome.reviewer) {
      const reviewStatus = outcome.reviewed ? "success" : outcome.summary.startsWith("Falha") ? "error" : "skipped";
      if (reviewStarted) {
        await repository?.updateRun(reviewRunId, {
          status: reviewStatus,
          output: outcome.reviewResult?.output,
          reason: outcome.reviewed ? undefined : outcome.summary,
          completedAt: new Date().toISOString(),
        });
      } else {
        await persistFinishedRun(repository, {
          runId: reviewRunId,
          taskId,
          stepIndex: plan.steps.length,
          provider: outcome.reviewer,
          purpose: `Revisão do resultado de ${lastSuccessful.provider}`,
          status: reviewStatus,
          output: outcome.reviewResult?.output,
          reason: outcome.reviewed ? undefined : outcome.summary,
        });
      }
    }
    if (outcome.reviewed && outcome.reviewResult) {
      const record = buildEvidenceRecord({
        taskId,
        runId: reviewRunId,
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

  const finalStatus = determineFinalTaskStatus(planCompleted, results, base.requiresApproval);
  await repository?.updateTask(taskId, {
    status: finalStatus,
    requiresApproval: base.requiresApproval,
    validation: validation
      ? {
          reviewed: validation.reviewed,
          status: validation.status,
          reviewer: validation.reviewer,
          summary: validation.summary,
        }
      : undefined,
    updatedAt: new Date().toISOString(),
  });
  return { ...base, results, evidence, validation };
}

function determineFinalTaskStatus(
  planCompleted: boolean,
  results: StepExecutionResult[],
  requiresApproval: boolean,
): "completed" | "awaiting_approval" | "failed" {
  if (requiresApproval) return "awaiting_approval";
  if (!planCompleted || !results.some((result) => result.status === "success")) return "failed";
  return "completed";
}

function combineEvidenceSinks(
  repository: OrchestrationRepository | undefined,
  explicitSink: EvidenceSink | undefined,
): EvidenceSink {
  if (!repository) return explicitSink ?? new InMemoryEvidenceSink();
  if (!explicitSink || explicitSink === repository) return repository;
  return {
    async record(record: EvidenceRecord): Promise<void> {
      await repository.record(record);
      await explicitSink.record(record);
    },
  };
}

async function persistFinishedRun(
  repository: OrchestrationRepository | undefined,
  params: {
    runId: string;
    taskId: string;
    stepIndex: number;
    provider: ProviderName;
    fallbackFor?: ProviderName;
    purpose: string;
    status: "success" | "error" | "skipped" | "blocked";
    output?: string;
    reason?: string;
  },
): Promise<void> {
  const now = new Date().toISOString();
  await repository?.createRun({
    id: params.runId,
    taskId: params.taskId,
    stepIndex: params.stepIndex,
    provider: params.provider,
    fallbackFor: params.fallbackFor,
    purpose: params.purpose,
    status: params.status,
    output: params.output,
    reason: params.reason,
    startedAt: now,
    completedAt: now,
  });
}

function providerCandidates(
  provider: ProviderName,
  primary: ProviderName,
  fallback: ProviderName | undefined,
): ProviderName[] {
  return provider === primary && fallback && fallback !== provider ? [provider, fallback] : [provider];
}

function requiresExplicitApproval(error: unknown): boolean {
  return (
    error instanceof Error &&
    "requiresApproval" in error &&
    (error as Error & { requiresApproval?: unknown }).requiresApproval === true
  );
}

const MAX_CONTEXT_CHARS = 40_000;
const MAX_PREVIOUS_OUTPUT_CHARS = 40_000;

function successfulOutputs(results: StepExecutionResult[]): Array<{ provider: ProviderName; output: string }> {
  return results.flatMap((result) =>
    result.status === "success" && result.output ? [{ provider: result.provider, output: result.output }] : [],
  );
}

function buildStepPrompt(
  task: string,
  purpose: string,
  projectFiles: Record<string, string>,
  previousResults: StepExecutionResult[],
): string {
  const sections = [`Tarefa original:\n${task}`, `Objetivo desta etapa:\n${purpose}`];
  const contextText = Object.entries(projectFiles)
    .map(([name, content]) => `### ${name}\n${content}`)
    .join("\n\n")
    .slice(0, MAX_CONTEXT_CHARS);
  if (contextText) {
    sections.push(`Contexto autorizado do projeto:\n${contextText}`);
  }

  const previousText = successfulOutputs(previousResults)
    .map(({ provider, output }) => `### Saída de ${provider}\n${output}`)
    .join("\n\n")
    .slice(0, MAX_PREVIOUS_OUTPUT_CHARS);
  if (previousText) {
    sections.push(`Resultados anteriores da cadeia:\n${previousText}`);
  }

  sections.push("Execute somente o objetivo desta etapa e preserve as evidências relevantes para a próxima etapa.");
  return sections.join("\n\n");
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
export * from "../persistence/index.js";
