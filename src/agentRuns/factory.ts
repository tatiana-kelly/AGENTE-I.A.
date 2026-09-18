/**
 * Monta as dependências do /v1/agent-runs a partir do ambiente, reutilizando o CostController existente.
 * Sem AGENT_RUN_HMAC_SECRET forte, devolve undefined e a rota responde 503 — fail-closed, sem workaround.
 *
 * Custo: o agent-run tem orçamento próprio, aprovado no contrato sal.agent-run/1.0 (até US$ 10 por chamada
 * e US$ 100 por job, declarados em cada requisição autenticada). Por isso a mesma classe CostController é
 * instanciada com esse teto, e NÃO com MAX_COST_PER_TASK_USD — que continua valendo só para o /orchestrate.
 * Tetos por provider também são próprios do agent-run: AGENT_RUN_<PROVIDER>_MAX_COST_PER_CALL_USD habilita
 * um provider aqui sem habilitá-lo no /orchestrate.
 */

import { CostController } from "../orchestrator/costController.js";
import type { ProviderManager } from "../orchestrator/providerManager.js";
import type { OrchestrationRepository } from "../persistence/index.js";
import type { ProviderName } from "../providers/types.js";
import { InMemoryNonceStore, loadAgentRunAuthFromEnv } from "./auth.js";
import { LIMITS } from "./contract.js";
import type { AgentRunHttpDependencies } from "./http.js";
import { AGENT_RUN_PROVIDER_ALLOWLIST, parseAgentRunProviders } from "./runner.js";
import { InMemoryAgentRunStore } from "./store.js";
import { buildAgentRunStoreFromEnv } from "./supabaseStore.js";

/** Lê AGENT_RUN_<PROVIDER>_MAX_COST_PER_CALL_USD; valores ausentes, inválidos ou acima do contrato são ignorados. */
export function parseAgentRunCostCaps(env: NodeJS.ProcessEnv = process.env): Partial<Record<ProviderName, number>> {
  const caps: Partial<Record<ProviderName, number>> = {};
  for (const provider of AGENT_RUN_PROVIDER_ALLOWLIST) {
    const raw = env[`AGENT_RUN_${provider.toUpperCase()}_MAX_COST_PER_CALL_USD`];
    const value = Number(raw);
    if (raw !== undefined && raw.trim() !== "" && Number.isFinite(value) && value > 0 && value <= LIMITS.maxCostPerCallUsd) {
      caps[provider] = value;
    }
  }
  return caps;
}

/** Teto técnico de tokens de saída por chamada aceito pelo agent-run. */
export const MAX_AGENT_RUN_OUTPUT_TOKENS = 32_000;

/** Lê AGENT_RUN_<PROVIDER>_MAX_OUTPUT_TOKENS; inteiros positivos até o teto técnico, o resto é ignorado. */
export function parseAgentRunOutputTokens(env: NodeJS.ProcessEnv = process.env): Partial<Record<ProviderName, number>> {
  const limits: Partial<Record<ProviderName, number>> = {};
  for (const provider of AGENT_RUN_PROVIDER_ALLOWLIST) {
    const raw = env[`AGENT_RUN_${provider.toUpperCase()}_MAX_OUTPUT_TOKENS`];
    const value = Number(raw);
    if (raw !== undefined && Number.isInteger(value) && value > 0 && value <= MAX_AGENT_RUN_OUTPUT_TOKENS) {
      limits[provider] = value;
    }
  }
  return limits;
}

export function buildAgentRunDependenciesFromEnv(
  repository: OrchestrationRepository,
  providerManager: ProviderManager,
  env: NodeJS.ProcessEnv = process.env,
): AgentRunHttpDependencies | undefined {
  const auth = loadAgentRunAuthFromEnv(env);
  if (!auth) return undefined;
  return {
    repository,
    providerManager,
    // Sem Supabase configurado, a idempotência vale apenas dentro do processo.
    store: buildAgentRunStoreFromEnv(env) ?? new InMemoryAgentRunStore(),
    costController: new CostController({
      maxCostPerTaskUsd: LIMITS.maxCostPerJobUsd,
      requireConfirmationAboveUsd: LIMITS.maxCostPerJobUsd,
      providerPriority: [...AGENT_RUN_PROVIDER_ALLOWLIST],
    }),
    // AGENT_RUN_PROVIDERS restringe a ordem; nada fora de anthropic/openai é aceito.
    allowedProviders: parseAgentRunProviders(env.AGENT_RUN_PROVIDERS),
    providerCostCaps: parseAgentRunCostCaps(env),
    providerMaxOutputTokens: parseAgentRunOutputTokens(env),
    auth,
    nonces: new InMemoryNonceStore(),
  };
}
