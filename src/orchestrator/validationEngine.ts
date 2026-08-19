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
  onReviewerCallStart?: (reviewer: ProviderName) => Promise<void>;
}

export interface ValidationOutcome {
  reviewed: boolean;
  status: ValidationStatus;
  summary: string;
  reviewer?: ProviderName;
  reviewResult?: TaskResult;
}

/** Uma rodada do ciclo revisar → (se REJECTED) corrigir → revisar de novo. */
export interface CorrectionAttempt {
  attempt: number;
  rejectionSummary: string;
  /** undefined quando a correção não pôde ser executada (custo, segurança ou falha do provider). */
  correctedOutput?: string;
  blockedReason?: string;
}

export interface ReviewCycleContext extends ValidationContext {
  /**
   * Pede ao provider que produziu o artefato uma nova versão, dado o feedback
   * do reviewer. Retorna `undefined` quando a chamada não foi autorizada
   * (orçamento/segurança) ou falhou — nesse caso o ciclo para e escala para
   * humano, nunca entrega o artefato rejeitado como se fosse aprovado.
   */
  requestCorrection?: (feedback: string, attempt: number) => Promise<TaskResult | undefined>;
  /** Default 1. Zero desliga o ciclo de correção (comportamento anterior). */
  maxCorrectionAttempts?: number;
}

export interface ReviewCycleOutcome extends ValidationOutcome {
  /** Resultado final aceito (corrigido ou original). */
  finalResult: TaskResult;
  corrections: CorrectionAttempt[];
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

  await context.onReviewerCallStart?.(routing.reviewer);
  try {
    const reviewResult = await providerManager.call(routing.reviewer, {
      taskId: taskInput.taskId,
      prompt: buildReviewPrompt(taskInput, primaryResult),
      project: taskInput.project,
      context: taskInput.context,
      skill: taskInput.skill,
      modelProfile: "critical",
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

function buildCorrectionPrompt(taskInput: TaskInput, rejected: TaskResult, feedback: string): string {
  return [
    `A tarefa original era: "${taskInput.prompt}"`,
    "",
    "Sua resposta anterior foi REPROVADA na revisão independente.",
    "",
    "Resposta anterior:",
    rejected.output,
    "",
    "Motivo da reprovação:",
    feedback,
    "",
    "Produza uma nova versão corrigindo especificamente o que foi apontado.",
    "Não repita a versão anterior nem justifique — entregue o resultado corrigido.",
  ].join("\n");
}

/**
 * Ciclo EXECUÇÃO → REVISÃO → (REJECTED) → CORREÇÃO → REVISÃO, com limite de
 * tentativas para não entrar em loop infinito (missão §8).
 *
 * Regras que o ciclo nunca quebra:
 * - Só corrige quando o veredito é REJECTED. NEEDS_HUMAN vai direto para
 *   humano — se a revisão não pôde ser feita com confiança, tentar de novo
 *   automaticamente só empilha incerteza.
 * - Correção não autorizada (orçamento/segurança) ou que falhe encerra o
 *   ciclo com o último veredito real; o artefato rejeitado nunca é
 *   promovido a aprovado.
 * - Esgotar as tentativas mantém o status REJECTED, que o orchestrator já
 *   trata como `requiresApproval`.
 */
export async function runReviewCycle(
  providerManager: ProviderManager,
  routing: RoutingDecision,
  taskInput: TaskInput,
  primaryResult: TaskResult,
  context: ReviewCycleContext,
): Promise<ReviewCycleOutcome> {
  const maxAttempts = context.maxCorrectionAttempts ?? 1;
  const corrections: CorrectionAttempt[] = [];

  let currentResult = primaryResult;
  let outcome = await validateResult(providerManager, routing, taskInput, currentResult, context);

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (outcome.status !== "REJECTED" || !context.requestCorrection) {
      break;
    }

    const feedback = outcome.summary;
    const corrected = await context.requestCorrection(
      buildCorrectionPrompt(taskInput, currentResult, feedback),
      attempt,
    );

    if (!corrected) {
      corrections.push({
        attempt,
        rejectionSummary: feedback,
        blockedReason: "Correção não executada (não autorizada por custo/segurança ou falha do provider).",
      });
      break;
    }

    corrections.push({ attempt, rejectionSummary: feedback, correctedOutput: corrected.output });
    currentResult = corrected;
    outcome = await validateResult(providerManager, routing, taskInput, currentResult, context);
  }

  return { ...outcome, finalResult: currentResult, corrections };
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
