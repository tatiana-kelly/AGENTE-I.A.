import { z } from "zod";
import type { ProviderName, TaskInput, TaskResult } from "../providers/types.js";
import type { ProviderManager } from "./providerManager.js";
import type { RoutingDecision, ValidationStatus } from "./types.js";

const reviewSchema = z.object({
  status: z.enum(["APPROVED", "REJECTED", "NEEDS_HUMAN"]),
  summary: z.string().min(1),
});

export interface ValidationContext {
  artifactProvider: ProviderName;
  authorizeReviewer?: (reviewer: ProviderName) => { allowed: boolean; reason: string };
}

export interface ValidationOutcome {
  reviewed: boolean;
  status: ValidationStatus;
  summary: string;
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
    `Fontes declaradas: ${JSON.stringify(primaryResult.sources)}`,
    `Evidências declaradas: ${JSON.stringify(primaryResult.evidence)}`,
    "",
    'Responda somente JSON: {"status":"APPROVED|REJECTED|NEEDS_HUMAN","summary":"justificativa curta"}.',
  ].join("\n");
}

/**
 * FASE 9 — runs the reviewer chain the Routing Engine assigned
 * (MANUS→CHATGPT, CLAUDE→CHATGPT, GEMINI→CHATGPT). Missing reviewers,
 * self-review, invalid output and provider failure all fail closed as
 * NEEDS_HUMAN.
 */
export async function validateResult(
  providerManager: ProviderManager,
  routing: RoutingDecision,
  taskInput: TaskInput,
  primaryResult: TaskResult,
  context: ValidationContext,
): Promise<ValidationOutcome> {
  if (!routing.reviewer) {
    return {
      reviewed: false,
      status: "NEEDS_HUMAN",
      summary: "Nenhum reviewer independente foi definido para este resultado.",
    };
  }

  if (routing.reviewer === context.artifactProvider) {
    return {
      reviewed: false,
      status: "NEEDS_HUMAN",
      reviewer: routing.reviewer,
      summary: `Autorrevisão bloqueada: ${routing.reviewer} produziu o artefato final.`,
    };
  }

  if (!providerManager.has(routing.reviewer)) {
    return {
      reviewed: false,
      status: "NEEDS_HUMAN",
      reviewer: routing.reviewer,
      summary: `Reviewer ${routing.reviewer} não está registrado.`,
    };
  }

  const authorization = context.authorizeReviewer?.(routing.reviewer);
  if (authorization && !authorization.allowed) {
    return {
      reviewed: false,
      status: "NEEDS_HUMAN",
      reviewer: routing.reviewer,
      summary: authorization.reason,
    };
  }

  try {
    const reviewResult = await providerManager.call(routing.reviewer, {
      taskId: taskInput.taskId,
      prompt: buildReviewPrompt(taskInput, primaryResult),
      project: taskInput.project,
      context: taskInput.context,
      skill: taskInput.skill,
    });
    const parsed = parseReview(reviewResult.output);
    if (!parsed) {
      return {
        reviewed: true,
        status: "NEEDS_HUMAN",
        reviewer: routing.reviewer,
        summary: "Reviewer retornou formato inválido; decisão encaminhada para revisão humana.",
        reviewResult,
      };
    }

    return { reviewed: true, reviewer: routing.reviewer, reviewResult, ...parsed };
  } catch (error) {
    return {
      reviewed: false,
      status: "NEEDS_HUMAN",
      reviewer: routing.reviewer,
      summary: `Falha ao executar reviewer: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

function parseReview(output: string): { status: ValidationStatus; summary: string } | undefined {
  const json = output.match(/\{[\s\S]*\}/)?.[0];
  if (!json) return undefined;
  try {
    const parsed = reviewSchema.safeParse(JSON.parse(json));
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}
