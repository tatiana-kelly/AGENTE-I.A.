import { describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, ModelProfile, TaskInput, TaskResult } from "./types.js";

export interface AnthropicProviderConfig {
  apiKey: string;
  /** Ajustar conforme o modelo vigente na conta — este é só um fallback. */
  model?: string;
  baseUrl?: string;
  timeoutMs?: number;
  maxTokens?: number;
  estimatedMaxCostUsd?: number;
  effort?: "low" | "medium" | "high" | "xhigh" | "max";
  models?: Partial<Record<ModelProfile, string>>;
}

const DEFAULT_MODEL = "claude-sonnet-5";
const DEFAULT_MAX_TOKENS = 4096;
const DEFAULT_BASE_URL = "https://api.anthropic.com/v1";
const ANTHROPIC_VERSION = "2023-06-01";

interface MessagesResponse {
  content: Array<{ type: string; text?: string }>;
  model: string;
  stop_reason?: string | null;
}

interface ModelsListResponse {
  data: Array<{ id: string }>;
}

/**
 * Provider Anthropic/Claude (FASE 2) — prioridade em programação,
 * debugging, refatoração, testes, implementação e GitHub (FASE 3).
 * Usa a Messages API diretamente via fetch.
 */
export class AnthropicProvider implements AIProvider {
  readonly name = "anthropic" as const;
  readonly capabilities;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly baseUrl: string;
  private readonly timeoutMs?: number;
  private readonly maxTokens: number;
  private readonly effort: "low" | "medium" | "high" | "xhigh" | "max";
  private readonly models: Record<ModelProfile, string>;

  constructor(config: AnthropicProviderConfig) {
    if (!config.apiKey) {
      throw new Error("AnthropicProvider requer apiKey (ANTHROPIC_API_KEY).");
    }
    this.apiKey = config.apiKey;
    this.model = config.model ?? DEFAULT_MODEL;
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    this.timeoutMs = config.timeoutMs;
    this.maxTokens = config.maxTokens ?? DEFAULT_MAX_TOKENS;
    this.effort = config.effort ?? "medium";
    this.models = {
      fast: config.models?.fast ?? "claude-sonnet-5",
      balanced: config.models?.balanced ?? config.model ?? "claude-sonnet-5",
      critical: config.models?.critical ?? "claude-opus-5",
      adversarial: config.models?.adversarial ?? "claude-fable-5",
      builder: config.models?.builder ?? "claude-opus-5",
    };
    this.capabilities = {
      mayProduceExternalEffects: false,
      estimatedMaxCostUsd: config.estimatedMaxCostUsd,
    } as const;
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    const model = this.models[input.modelProfile ?? "balanced"];
    const response = await fetchJson<MessagesResponse>(`${this.baseUrl}/messages`, {
      method: "POST",
      timeoutMs: this.timeoutMs,
      headers: {
        "content-type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": ANTHROPIC_VERSION,
      },
      body: JSON.stringify({
        model,
        max_tokens: this.maxTokens,
        thinking: { type: "adaptive" },
        output_config: { effort: this.effort },
        messages: [{ role: "user", content: input.prompt }],
      }),
    });

    if (response.stop_reason === "max_tokens") {
      throw new Error(
        `Resposta Anthropic truncada em max_tokens=${this.maxTokens}; o resultado incompleto foi descartado.`,
      );
    }

    const output = response.content
      .filter((block) => block.type === "text" && block.text)
      .map((block) => block.text)
      .join("\n");

    return { output, model: response.model ?? model, sources: [], evidence: [], raw: response };
  }

  async healthCheck(): Promise<HealthStatus> {
    const checkedAt = new Date().toISOString();
    const start = performance.now();
    try {
      await fetchJson<ModelsListResponse>(`${this.baseUrl}/models`, {
        timeoutMs: this.timeoutMs ?? 10_000,
        headers: { "x-api-key": this.apiKey, "anthropic-version": ANTHROPIC_VERSION },
      });
      return { healthy: true, latencyMs: performance.now() - start, checkedAt };
    } catch (error) {
      return { healthy: false, latencyMs: performance.now() - start, message: describeProviderError(error), checkedAt };
    }
  }
}
