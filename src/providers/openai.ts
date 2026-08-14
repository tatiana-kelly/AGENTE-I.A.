import { describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, TaskInput, TaskResult } from "./types.js";

export interface OpenAIProviderConfig {
  apiKey: string;
  /** Ajustar conforme o catálogo de modelos vigente na conta — este é só um fallback. */
  model?: string;
  baseUrl?: string;
  timeoutMs?: number;
}

const DEFAULT_MODEL = "gpt-4o-mini";
const DEFAULT_BASE_URL = "https://api.openai.com/v1";

interface ChatCompletionResponse {
  choices: Array<{ message: { content: string | null }; finish_reason: string }>;
  model: string;
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
  private readonly apiKey: string;
  private readonly model: string;
  private readonly baseUrl: string;
  private readonly timeoutMs?: number;

  constructor(config: OpenAIProviderConfig) {
    if (!config.apiKey) {
      throw new Error("OpenAIProvider requer apiKey (OPENAI_API_KEY).");
    }
    this.apiKey = config.apiKey;
    this.model = config.model ?? DEFAULT_MODEL;
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    this.timeoutMs = config.timeoutMs;
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    const response = await fetchJson<ChatCompletionResponse>(`${this.baseUrl}/chat/completions`, {
      method: "POST",
      timeoutMs: this.timeoutMs,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages: [{ role: "user", content: input.prompt }],
      }),
    });

    return {
      output: response.choices[0]?.message.content ?? "",
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
