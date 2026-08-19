import { ProviderManager } from "../orchestrator/providerManager.js";
import { AnthropicProvider } from "./anthropic.js";
import { GeminiProvider } from "./gemini.js";
import { ManusProvider } from "./manus.js";
import { OpenAIProvider } from "./openai.js";
import type { ProviderName } from "./types.js";

export * from "./types.js";
export { ProviderHttpError, describeProviderError } from "./httpClient.js";
export { OpenAIProvider } from "./openai.js";
export { AnthropicProvider } from "./anthropic.js";
export { GeminiProvider } from "./gemini.js";
export { ManusProvider, ManusTaskWaitingError } from "./manus.js";

export interface BuildProvidersResult {
  manager: ProviderManager;
  registered: ProviderName[];
  skipped: ProviderName[];
}

/**
 * Registra no Provider Manager só os providers cuja API key existe no
 * ambiente (FASE 2). Nenhuma chave é obrigatória para o orchestrator
 * subir — o que faltar entra em `skipped`; quem chama decide se loga
 * isso via Observability ou trata como erro fatal.
 */
export function buildProviderManagerFromEnv(env: NodeJS.ProcessEnv = process.env): BuildProvidersResult {
  const manager = new ProviderManager();
  const registered: ProviderName[] = [];
  const skipped: ProviderName[] = [];

  if (env.OPENAI_API_KEY) {
    manager.register(
      new OpenAIProvider({
        apiKey: env.OPENAI_API_KEY,
        model: env.OPENAI_MODEL,
        models: {
          fast: env.OPENAI_MODEL_FAST,
          balanced: env.OPENAI_MODEL_BALANCED,
          critical: env.OPENAI_MODEL_CRITICAL,
          adversarial: env.OPENAI_MODEL_ADVERSARIAL,
          builder: env.OPENAI_MODEL_BUILDER,
        },
        reasoningEffort: parseOpenAIReasoningEffort(env.OPENAI_REASONING_EFFORT),
        maxOutputTokens: numberOrUndefined(env.OPENAI_MAX_OUTPUT_TOKENS),
        estimatedMaxCostUsd: numberOrUndefined(env.OPENAI_MAX_COST_PER_CALL_USD),
      }),
    );
    registered.push("openai");
  } else {
    skipped.push("openai");
  }

  if (env.ANTHROPIC_API_KEY) {
    manager.register(
      new AnthropicProvider({
        apiKey: env.ANTHROPIC_API_KEY,
        model: env.ANTHROPIC_MODEL,
        models: {
          fast: env.ANTHROPIC_MODEL_FAST,
          balanced: env.ANTHROPIC_MODEL_BALANCED,
          critical: env.ANTHROPIC_MODEL_CRITICAL,
          adversarial: env.ANTHROPIC_MODEL_ADVERSARIAL,
          builder: env.ANTHROPIC_MODEL_BUILDER,
        },
        effort: parseAnthropicEffort(env.ANTHROPIC_EFFORT),
        maxTokens: numberOrUndefined(env.ANTHROPIC_MAX_OUTPUT_TOKENS),
        estimatedMaxCostUsd: numberOrUndefined(env.ANTHROPIC_MAX_COST_PER_CALL_USD),
      }),
    );
    registered.push("anthropic");
  } else {
    skipped.push("anthropic");
  }

  if (env.GEMINI_API_KEY) {
    manager.register(
      new GeminiProvider({
        apiKey: env.GEMINI_API_KEY,
        model: env.GEMINI_MODEL,
        estimatedMaxCostUsd: numberOrUndefined(env.GEMINI_MAX_COST_PER_CALL_USD),
      }),
    );
    registered.push("gemini");
  } else {
    skipped.push("gemini");
  }

  if (env.MANUS_API_KEY) {
    manager.register(
      new ManusProvider({
        apiKey: env.MANUS_API_KEY,
        agentProfile: env.MANUS_AGENT_PROFILE,
        pollIntervalMs: numberOrUndefined(env.MANUS_POLL_INTERVAL_MS),
        pollTimeoutMs: numberOrUndefined(env.MANUS_POLL_TIMEOUT_MS),
        estimatedMaxCostUsd: numberOrUndefined(env.MANUS_MAX_COST_PER_CALL_USD),
      }),
    );
    registered.push("manus");
  } else {
    skipped.push("manus");
  }

  return { manager, registered, skipped };
}

function numberOrUndefined(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseOpenAIReasoningEffort(
  value: string | undefined,
): "none" | "low" | "medium" | "high" | "xhigh" | "max" | undefined {
  return value === "none" || value === "low" || value === "medium" || value === "high" || value === "xhigh" || value === "max"
    ? value
    : undefined;
}

function parseAnthropicEffort(
  value: string | undefined,
): "low" | "medium" | "high" | "xhigh" | "max" | undefined {
  return value === "low" || value === "medium" || value === "high" || value === "xhigh" || value === "max"
    ? value
    : undefined;
}
