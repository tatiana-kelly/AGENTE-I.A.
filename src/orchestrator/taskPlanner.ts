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
  const { requiresGoogleWorkspace, requiresInvestigation, requiresDecision, requiresImplementation, requiresAdversarialReview } = classification;

  if (requiresAdversarialReview) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "openai", purpose: "produzir análise-base como auditor principal", modelProfile: "critical" },
        { provider: "anthropic", purpose: "contestar achados como auditor adversarial", modelProfile: "adversarial" },
        { provider: "openai", purpose: "arbitrar divergências e consolidar o resultado", modelProfile: "critical" },
      ],
    };
  }

  if (requiresInvestigation && requiresImplementation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "manus", purpose: "investigar/pesquisar" },
        { provider: "openai", purpose: "decidir a melhor abordagem", modelProfile: "critical" },
        { provider: "anthropic", purpose: "construir a solução aprovada", modelProfile: "builder" },
        { provider: "openai", purpose: "validar o resultado construído", modelProfile: "critical" },
      ],
    };
  }

  if (requiresGoogleWorkspace && requiresInvestigation) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "gemini", purpose: "coletar/organizar dados do Google Workspace" },
        { provider: "manus", purpose: "investigar e cruzar informações" },
        { provider: "openai", purpose: "interpretar e decidir", modelProfile: "balanced" },
      ],
    };
  }

  if (requiresInvestigation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "manus", purpose: "investigar/pesquisar" },
        { provider: "openai", purpose: "tomar a decisão", modelProfile: "critical" },
      ],
    };
  }

  if (requiresImplementation && requiresDecision) {
    return {
      mode: "MULTI_AGENT",
      steps: [
        { provider: "openai", purpose: "decidir a melhor abordagem", modelProfile: "critical" },
        { provider: "anthropic", purpose: "construir a solução", modelProfile: "builder" },
        { provider: "openai", purpose: "validar o resultado", modelProfile: "critical" },
      ],
    };
  }

  return {
    mode: "ONE_AGENT",
    steps: [{ provider: routing.primary, purpose: routing.reason, modelProfile: defaultProfile(routing.primary, classification) }],
  };
}

function defaultProfile(
  provider: RoutingDecision["primary"],
  classification: ClassificationResult,
): "fast" | "balanced" | "critical" | "builder" {
  if (provider === "openai") return classification.requiresDecision ? "critical" : "balanced";
  if (provider === "anthropic") return classification.requiresImplementation ? "builder" : "balanced";
  return "fast";
}
