import type {
  AIProvider,
  HealthStatus,
  ProviderCapabilities,
  ProviderName,
  TaskInput,
  TaskResult,
} from "../providers/types.js";

export class ProviderNotRegisteredError extends Error {
  constructor(public readonly provider: ProviderName) {
    super(`Provider "${provider}" não está registrado no Provider Manager.`);
    this.name = "ProviderNotRegisteredError";
  }
}

/**
 * FASE 2/3 — registry that the Routing Engine's decisions get dispatched
 * through. The Router never imports a concrete provider directly; concrete
 * `AIProvider` implementations (FASE 2: openai/manus/anthropic/gemini) are
 * registered here at app startup.
 */
export class ProviderManager {
  private readonly providers = new Map<ProviderName, AIProvider>();

  register(provider: AIProvider): void {
    this.providers.set(provider.name, provider);
  }

  has(name: ProviderName): boolean {
    return this.providers.has(name);
  }

  capabilities(name: ProviderName): ProviderCapabilities {
    const provider = this.providers.get(name);
    if (!provider) {
      throw new ProviderNotRegisteredError(name);
    }
    return provider.capabilities;
  }

  async healthCheckAll(): Promise<Partial<Record<ProviderName, HealthStatus>>> {
    const entries = await Promise.all(
      Array.from(this.providers.values()).map(
        async (provider) => [provider.name, await provider.healthCheck()] as const,
      ),
    );
    return Object.fromEntries(entries);
  }

  async call(name: ProviderName, input: TaskInput): Promise<TaskResult> {
    const provider = this.providers.get(name);
    if (!provider) {
      throw new ProviderNotRegisteredError(name);
    }
    return provider.analyze(input);
  }
}
