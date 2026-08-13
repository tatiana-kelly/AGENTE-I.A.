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

  evaluate(estimatedCostUsd: number | undefined): CostEvaluation {
    if (estimatedCostUsd === undefined) {
      return {
        estimatedCostUsd: "unknown",
        withinBudget: true,
        requiresConfirmation: false,
        reason: "Custo estimado indisponível para este provider (sem métrica reportada) — tratado como unknown, não como zero.",
      };
    }

    const withinBudget = estimatedCostUsd <= this.config.maxCostPerTaskUsd;
    const requiresConfirmation = estimatedCostUsd > this.config.requireConfirmationAboveUsd;

    let reason: string;
    if (!withinBudget) {
      reason = `Custo estimado (US$ ${estimatedCostUsd.toFixed(2)}) excede o máximo por tarefa (US$ ${this.config.maxCostPerTaskUsd.toFixed(2)}).`;
    } else if (requiresConfirmation) {
      reason = `Custo estimado (US$ ${estimatedCostUsd.toFixed(2)}) acima do limite de confirmação automática (US$ ${this.config.requireConfirmationAboveUsd.toFixed(2)}).`;
    } else {
      reason = "Dentro do orçamento, sem necessidade de confirmação.";
    }

    return { estimatedCostUsd, withinBudget, requiresConfirmation, reason };
  }
}

export function loadCostControlConfigFromEnv(env: NodeJS.ProcessEnv = process.env): CostControlConfig {
  return {
    maxCostPerTaskUsd: Number(env.MAX_COST_PER_TASK_USD ?? "1.00"),
    requireConfirmationAboveUsd: Number(env.REQUIRE_CONFIRMATION_ABOVE_USD ?? "0.50"),
    providerPriority: ["openai", "manus", "anthropic", "gemini"],
  };
}
