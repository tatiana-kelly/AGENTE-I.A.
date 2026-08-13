import type { ProviderName, TaskInput, TaskResult } from "../providers/types.js";
import type { ProviderManager } from "./providerManager.js";
import type { RoutingDecision } from "./types.js";

export interface ValidationOutcome {
  reviewed: boolean;
  reviewer?: ProviderName;
  reviewResult?: TaskResult;
}

function buildReviewPrompt(taskInput: TaskInput, primaryResult: TaskResult): string {
  return [
    `Revise o resultado abaixo para a tarefa: "${taskInput.prompt}"`,
    "",
    "Resultado a revisar:",
    primaryResult.output,
    "",
    "Aponte inconsistências, riscos ou lacunas. Se estiver correto, confirme explicitamente.",
  ].join("\n");
}

/**
 * FASE 9 — runs the reviewer chain the Routing Engine assigned
 * (MANUS→CHATGPT, CLAUDE→CHATGPT, GEMINI→CHATGPT). No-op when the routing
 * decision didn't assign a reviewer, or the reviewer provider isn't
 * registered yet (reported, not silently swallowed).
 */
export async function validateResult(
  providerManager: ProviderManager,
  routing: RoutingDecision,
  taskInput: TaskInput,
  primaryResult: TaskResult,
): Promise<ValidationOutcome> {
  if (!routing.reviewer) {
    return { reviewed: false };
  }

  if (!providerManager.has(routing.reviewer)) {
    return { reviewed: false, reviewer: routing.reviewer };
  }

  const reviewResult = await providerManager.call(routing.reviewer, {
    taskId: taskInput.taskId,
    prompt: buildReviewPrompt(taskInput, primaryResult),
    project: taskInput.project,
    skill: taskInput.skill,
  });

  return { reviewed: true, reviewer: routing.reviewer, reviewResult };
}
