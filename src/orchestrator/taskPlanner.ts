import type { ClassificationResult, RoutingDecision, TaskPlan } from "./types.js";

/**
 * FASE 4 — decides ONE_AGENT vs MULTI_AGENT and orders the provider chain.
 * Only the chains with clear, documented signal in the PRP are encoded here
 * (Google data, investigation+decision, implementation+decision); anything
 * else is a single-step plan around the Routing Engine's primary decision.
 * Extend this table as real usage surfaces new recurring chains — don't
 * guess additional chains without evidence.
 */
export function planTask(classification: ClassificationResult, routing: RoutingDecision): TaskPlan {
  const { requiresGoogleWorkspace, requiresInvestigation, requiresDecision, requiresImplementation } = classification;

  if (requiresInvestigation && requiresImplementation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "manus", purpose: "investigar/pesquisar" },
        { provider: "openai", purpose: "decidir a melhor abordagem" },
        { provider: "anthropic", purpose: "construir a solução aprovada" },
        { provider: "openai", purpose: "validar o resultado construído" },
      ],
    };
  }

  if (requiresGoogleWorkspace && requiresInvestigation) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "gemini", purpose: "coletar/organizar dados do Google Workspace" },
        { provider: "manus", purpose: "investigar e cruzar informações" },
        { provider: "openai", purpose: "interpretar e decidir" },
      ],
    };
  }

  if (requiresInvestigation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "manus", purpose: "investigar/pesquisar" },
        { provider: "openai", purpose: "tomar a decisão" },
      ],
    };
  }

  if (requiresImplementation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "openai", purpose: "decidir a melhor abordagem" },
        { provider: "anthropic", purpose: "construir a solução" },
        { provider: "openai", purpose: "validar o resultado" },
      ],
    };
  }

  return {
    mode: "ONE_AGENT",
    steps: [{ provider: routing.primary, purpose: routing.reason }],
  };
}
