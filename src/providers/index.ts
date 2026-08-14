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
export { ManusProvider } from "./manus.js";

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
    manager.register(new OpenAIProvider({ apiKey: env.OPENAI_API_KEY, model: env.OPENAI_MODEL }));
    registered.push("openai");
  } else {
    skipped.push("openai");
  }

  if (env.ANTHROPIC_API_KEY) {
    manager.register(new AnthropicProvider({ apiKey: env.ANTHROPIC_API_KEY, model: env.ANTHROPIC_MODEL }));
    registered.push("anthropic");
  } else {
    skipped.push("anthropic");
  }

  if (env.GEMINI_API_KEY) {
    manager.register(new GeminiProvider({ apiKey: env.GEMINI_API_KEY, model: env.GEMINI_MODEL }));
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
