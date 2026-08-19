import { describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, ModelProfile, TaskInput, TaskResult } from "./types.js";

export interface OpenAIProviderConfig {
  apiKey: string;
  /** Ajustar conforme o catálogo de modelos vigente na conta — este é só um fallback. */
  model?: string;
  baseUrl?: string;
  timeoutMs?: number;
  estimatedMaxCostUsd?: number;
  reasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh" | "max";
  models?: Partial<Record<ModelProfile, string>>;
  maxOutputTokens?: number;
}

const DEFAULT_MODEL = "gpt-5.6-sol";
const DEFAULT_BASE_URL = "https://api.openai.com/v1";

interface ResponsesApiResponse {
  output: Array<{ type: string; content?: Array<{ type: string; text?: string }> }>;
  model: string;
  status?: string;
  incomplete_details?: { reason?: string } | null;
}

interface ModelsListResponse {
  data: Array<{ id: string }>;
}

/**
 * Provider OpenAI/ChatGPT (FASE 2) — prioridade em estratégia, análise
 * executiva, arquitetura, crítica e validação (FASE 3). Usa a Chat
 * Completions API diretamente via fetch.
 */
export class OpenAIProvider implements AIProvider {
  readonly name = "openai" as const;
  readonly capabilities;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly baseUrl: string;
  private readonly timeoutMs?: number;
  private readonly reasoningEffort: "none" | "low" | "medium" | "high" | "xhigh" | "max";
  private readonly models: Record<ModelProfile, string>;
  private readonly maxOutputTokens: number;

  constructor(config: OpenAIProviderConfig) {
    if (!config.apiKey) {
      throw new Error("OpenAIProvider requer apiKey (OPENAI_API_KEY).");
    }
    this.apiKey = config.apiKey;
    this.model = config.model ?? DEFAULT_MODEL;
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    this.timeoutMs = config.timeoutMs;
    this.reasoningEffort = config.reasoningEffort ?? "medium";
    this.models = {
      fast: config.models?.fast ?? "gpt-5.6-luna",
      balanced: config.models?.balanced ?? config.model ?? "gpt-5.6-terra",
      critical: config.models?.critical ?? "gpt-5.6-sol",
      adversarial: config.models?.adversarial ?? "gpt-5.6-sol",
      builder: config.models?.builder ?? "gpt-5.6-sol",
    };
    this.maxOutputTokens = config.maxOutputTokens ?? 4096;
    this.capabilities = {
      mayProduceExternalEffects: false,
      estimatedMaxCostUsd: config.estimatedMaxCostUsd,
    } as const;
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    const model = this.models[input.modelProfile ?? "balanced"];
    const response = await fetchJson<ResponsesApiResponse>(`${this.baseUrl}/responses`, {
      method: "POST",
      timeoutMs: this.timeoutMs,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model,
        input: input.prompt,
        reasoning: { effort: this.reasoningEffort },
        max_output_tokens: this.maxOutputTokens,
      }),
    });

    if (response.status === "incomplete") {
      throw new Error(`Resposta OpenAI incompleta: ${response.incomplete_details?.reason ?? "motivo não informado"}.`);
    }

    const output = response.output
      .filter((item) => item.type === "message")
      .flatMap((item) => item.content ?? [])
      .filter((content) => content.type === "output_text")
      .map((content) => content.text ?? "")
      .join("\n");

    return {
      output,
      model: response.model ?? model,
      sources: [],
      evidence: [],
      raw: response,
    };
  }

  async healthCheck(): Promise<HealthStatus> {
    const checkedAt = new Date().toISOString();
    const start = performance.now();
    try {
      await fetchJson<ModelsListResponse>(`${this.baseUrl}/models`, {
        timeoutMs: this.timeoutMs ?? 10_000,
        headers: { authorization: `Bearer ${this.apiKey}` },
      });
      return { healthy: true, latencyMs: performance.now() - start, checkedAt };
    } catch (error) {
      return { healthy: false, latencyMs: performance.now() - start, message: describeProviderError(error), checkedAt };
    }
  }
}
