import type { ProviderName } from "../providers/types.js";

/** FASE 16 — deliberately simple. No billing engine in this version. */
export interface CostControlConfig {
  maxCostPerTaskUsd: number;
  requireConfirmationAboveUsd: number;
  providerPriority: ProviderName[];
}

export interface CostEvaluation {
  /** "unknown" when the provider hasn't reported a real cost — FASE 17: never invent metrics. */
  estimatedCostUsd: number | "unknown";
  withinBudget: boolean;
  requiresConfirmation: boolean;
  reason: string;
}

export class CostController {
  constructor(private readonly config: CostControlConfig) {}

  evaluate(estimatedCostUsd: number | undefined, approvedMaxCostUsd?: number): CostEvaluation {
    if (estimatedCostUsd === undefined) {
      return {
        estimatedCostUsd: "unknown",
        withinBudget: false,
        requiresConfirmation: true,
        reason: "Custo máximo indisponível para este provider — chamada bloqueada até existir limite explícito.",
      };
    }

    if (!Number.isFinite(estimatedCostUsd) || estimatedCostUsd < 0) {
      return {
        estimatedCostUsd: "unknown",
        withinBudget: false,
        requiresConfirmation: true,
        reason: "Estimativa de custo inválida — chamada bloqueada por segurança.",
      };
    }

    const withinBudget = estimatedCostUsd <= this.config.maxCostPerTaskUsd;
    const confirmationCoversEstimate =
      approvedMaxCostUsd !== undefined &&
      Number.isFinite(approvedMaxCostUsd) &&
      approvedMaxCostUsd >= 0 &&
      estimatedCostUsd <= approvedMaxCostUsd;
    const requiresConfirmation =
      estimatedCostUsd > this.config.requireConfirmationAboveUsd && !confirmationCoversEstimate;

    let reason: string;
    if (!withinBudget) {
      reason = `Custo estimado (US$ ${estimatedCostUsd.toFixed(2)}) excede o máximo por tarefa (US$ ${this.config.maxCostPerTaskUsd.toFixed(2)}).`;
    } else if (requiresConfirmation) {
      reason = `Custo estimado (US$ ${estimatedCostUsd.toFixed(2)}) acima do limite de confirmação automática (US$ ${this.config.requireConfirmationAboveUsd.toFixed(2)}).`;
    } else if (estimatedCostUsd > this.config.requireConfirmationAboveUsd) {
      reason = `Custo estimado (US$ ${estimatedCostUsd.toFixed(2)}) coberto pela aprovação explícita.`;
    } else {
      reason = "Dentro do orçamento, sem necessidade de confirmação.";
    }

    return { estimatedCostUsd, withinBudget, requiresConfirmation, reason };
  }
}

export function loadCostControlConfigFromEnv(env: NodeJS.ProcessEnv = process.env): CostControlConfig {
  const maxCostPerTaskUsd = positiveNumberOrDefault(env.MAX_COST_PER_TASK_USD, 1);
  const requestedConfirmation = positiveNumberOrDefault(env.REQUIRE_CONFIRMATION_ABOVE_USD, 0.5);
  return {
    maxCostPerTaskUsd,
    requireConfirmationAboveUsd: Math.min(requestedConfirmation, maxCostPerTaskUsd),
    providerPriority: ["openai", "manus", "anthropic", "gemini"],
  };
}

function positiveNumberOrDefault(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}
