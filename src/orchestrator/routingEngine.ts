import type { ProviderName } from "../providers/types.js";
import type { ClassificationResult, RoutingDecision, SkillCategory } from "./types.js";

/** FASE 3 — default provider per skill when no stronger execution-flag signal applies. */
const SKILL_DEFAULT_PROVIDER: Record<SkillCategory, ProviderName> = {
  "business-analysis": "openai",
  "financial-analysis": "openai",
  architecture: "openai",
  "data-analysis": "manus",
  research: "manus",
  "operational-analysis": "manus",
  presentation: "manus",
  programming: "anthropic",
  debugging: "anthropic",
  automation: "anthropic",
};

const PROVIDER_PRIORITY: ProviderName[] = ["openai", "manus", "anthropic", "gemini"];

function pickBySkillVote(skills: SkillCategory[]): { provider: ProviderName; reason: string } {
  const votes = new Map<ProviderName, number>();
  for (const skill of skills) {
    const provider = SKILL_DEFAULT_PROVIDER[skill];
    votes.set(provider, (votes.get(provider) ?? 0) + 1);
  }

  let best: ProviderName = "manus";
  let bestCount = -1;
  for (const provider of PROVIDER_PRIORITY) {
    const count = votes.get(provider) ?? 0;
    if (count > bestCount) {
      best = provider;
      bestCount = count;
    }
  }

  return { provider: best, reason: `skills: ${skills.join(", ") || "nenhuma"}` };
}

/**
 * FASE 3 routing matrix. Check order encodes priority: an explicit
 * execution-flag signal (Google Workspace, implementation, decision,
 * investigation) always wins over the generic skill-vote fallback.
 * Default reviewer assignment follows the FASE 9 validation matrix
 * (MANUS→CHATGPT, CLAUDE→CHATGPT, GEMINI→CHATGPT) — OpenAI-led tasks
 * don't get a reviewer because OpenAI is already the reviewer role.
 */
export function routeTask(classification: ClassificationResult): RoutingDecision {
  const { skills, requiresGoogleWorkspace, requiresInvestigation, requiresImplementation, requiresDecision } =
    classification;

  if (classification.requiresAdversarialReview) {
    return {
      primary: "openai",
      reviewer: "anthropic",
      reason: "Auditoria adversarial: GPT-5.6 Sol lidera/arbitra e Claude Fable 5 contesta.",
      confidence: 0.95,
      fallback: "anthropic",
    };
  }

  if (requiresGoogleWorkspace) {
    return {
      primary: "gemini",
      reviewer: "openai",
      reason: "Tarefa depende do ecossistema Google Workspace.",
      confidence: 0.9,
      fallback: "manus",
    };
  }

  if (requiresImplementation) {
    return {
      primary: "anthropic",
      reviewer: "openai",
      reason: "Tarefa de programação/debugging/implementação — prioridade Claude Code.",
      confidence: 0.9,
      fallback: "openai",
    };
  }

  if (requiresInvestigation && (skills.includes("business-analysis") || skills.includes("financial-analysis"))) {
    return {
      primary: "manus",
      reviewer: "openai",
      reason: "Investigação com necessidade de interpretação/decisão de negócio.",
      confidence: 0.85,
      fallback: "openai",
    };
  }

  if (requiresInvestigation) {
    return {
      primary: "manus",
      reason: "Investigação/pesquisa exploratória.",
      confidence: 0.8,
      fallback: "openai",
    };
  }

  if (requiresDecision) {
    return {
      primary: "openai",
      reason: "Tomada de decisão / análise estratégica.",
      confidence: 0.85,
      fallback: "manus",
    };
  }

  if (skills.includes("architecture")) {
    return {
      primary: "openai",
      reason: "Definição de arquitetura.",
      confidence: 0.8,
      fallback: "anthropic",
    };
  }

  const { provider, reason } = pickBySkillVote(skills);
  return {
    primary: provider,
    reviewer: provider === "openai" ? undefined : "openai",
    reason: `Sem sinal forte de execução; roteado por skill dominante (${reason}).`,
    confidence: 0.6,
    fallback: provider === "openai" ? "manus" : "openai",
  };
}
