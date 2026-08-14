import { describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, TaskInput, TaskResult } from "./types.js";

export interface GeminiProviderConfig {
  apiKey: string;
  /** Ajustar conforme o modelo vigente na conta — este é só um fallback. */
  model?: string;
  baseUrl?: string;
  timeoutMs?: number;
}

const DEFAULT_MODEL = "gemini-2.5-flash";
const DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta";

interface GenerateContentResponse {
  candidates: Array<{ content: { parts: Array<{ text?: string }> } }>;
}

interface ModelsListResponse {
  models: Array<{ name: string }>;
}

/**
 * Provider Gemini (FASE 2) — prioridade em Google Drive/Sheets/Gmail/
 * Calendar/Workspace (FASE 3). Usa a Generative Language API diretamente
 * via fetch. A API key vai como query param `?key=` — esse é o mecanismo
 * de autenticação oficial da própria API do Google, não uma escolha
 * nossa; nunca logar a URL completa por causa disso.
 */
export class GeminiProvider implements AIProvider {
  readonly name = "gemini" as const;
  private readonly apiKey: string;
  private readonly model: string;
  private readonly baseUrl: string;
  private readonly timeoutMs?: number;

  constructor(config: GeminiProviderConfig) {
    if (!config.apiKey) {
      throw new Error("GeminiProvider requer apiKey (GEMINI_API_KEY).");
    }
    this.apiKey = config.apiKey;
    this.model = config.model ?? DEFAULT_MODEL;
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    this.timeoutMs = config.timeoutMs;
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    const response = await fetchJson<GenerateContentResponse>(
      `${this.baseUrl}/models/${this.model}:generateContent?key=${this.apiKey}`,
      {
        method: "POST",
        timeoutMs: this.timeoutMs,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          contents: [{ role: "user", parts: [{ text: input.prompt }] }],
        }),
      },
    );

    const output = (response.candidates[0]?.content.parts ?? [])
      .map((part) => part.text ?? "")
      .join("");

    return { output, sources: [], evidence: [], raw: response };
  }

  async healthCheck(): Promise<HealthStatus> {
    const checkedAt = new Date().toISOString();
    const start = performance.now();
    try {
      await fetchJson<ModelsListResponse>(`${this.baseUrl}/models?key=${this.apiKey}`, {
        timeoutMs: this.timeoutMs ?? 10_000,
      });
      return { healthy: true, latencyMs: performance.now() - start, checkedAt };
    } catch (error) {
      return { healthy: false, latencyMs: performance.now() - start, message: describeProviderError(error), checkedAt };
    }
  }
}
