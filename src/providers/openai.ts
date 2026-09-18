import { ProviderCallError } from "./callError.js";
import { ProviderHttpError, describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, ModelProfile, TaskInput, TaskResult } from "./types.js";

export interface OpenAIProviderConfig {
  apiKey: string;
  /** Ajustar conforme o catálogo de modelos vigente na conta — este é só um fallback. */
  model?: string;
  baseUrl?: string;
  timeoutMs?: number;
  estimatedMaxCostUsd?: number;
  reasoningEffort?: "none" | "low" | "medium" | "high" | "xhigh" | "max";
  /** Modelos que recusam `reasoning.effort` (OPENAI_MODELS_WITHOUT_REASONING), somados aos observados. */
  modelsWithoutReasoning?: string[];
  models?: Partial<Record<ModelProfile, string>>;
  maxOutputTokens?: number;
}

const DEFAULT_MODEL = "gpt-5.6-sol";

/**
 * Modelos que COMPROVADAMENTE recusam `reasoning.effort`. Única fonte: resposta real da API
 * (HTTP 400 unsupported_parameter, param "reasoning.effort") em 2026-09-18, no fallback do agent-run.
 * `gpt-5.6-sol` comprovadamente ACEITA (revisões reais de 2026-09-18). Modelos não listados seguem
 * recebendo o parâmetro; se recusarem, o provider aprende e repete uma vez sem ele.
 */
export const MODELS_WITHOUT_REASONING: readonly string[] = ["gpt-5.6-terra"];

function isReasoningUnsupported(error: unknown): boolean {
  if (!(error instanceof ProviderHttpError) || error.status !== 400) return false;
  const detail = (error.body as { error?: { param?: string; code?: string } } | undefined)?.error;
  return detail?.param === "reasoning.effort" && detail.code === "unsupported_parameter";
}
const DEFAULT_BASE_URL = "https://api.openai.com/v1";

interface ResponsesApiResponse {
  output: Array<{ type: string; content?: Array<{ type: string; text?: string }> }>;
  model: string;
  status?: string;
  incomplete_details?: { reason?: string } | null;
  /** Formato da Responses API (difere do chat/completions: input/output, não prompt/completion). */
  usage?: { input_tokens: number; output_tokens: number };
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
  private readonly modelsWithoutReasoning: Set<string>;
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
    this.modelsWithoutReasoning = new Set([...MODELS_WITHOUT_REASONING, ...(config.modelsWithoutReasoning ?? [])]);
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
    const withReasoning = !this.modelsWithoutReasoning.has(model);
    let attempts = 1;
    let response: ResponsesApiResponse;
    try {
      response = await this.request(input, model, withReasoning);
    } catch (error) {
      // Modelo recusou `reasoning.effort` (HTTP 400, recusado ANTES de processar): lembra o modelo e repete
      // UMA vez sem o parâmetro. Qualquer outro erro sobe intacto.
      if (!withReasoning || !isReasoningUnsupported(error)) throw error;
      this.modelsWithoutReasoning.add(model);
      attempts = 2;
      response = await this.request(input, model, false);
    }

    const usage = response.usage
      ? { inputTokens: response.usage.input_tokens, outputTokens: response.usage.output_tokens }
      : undefined;
    if (response.status === "incomplete") {
      throw new ProviderCallError(
        "incomplete",
        `Resposta OpenAI incompleta: ${response.incomplete_details?.reason ?? "motivo não informado"}.`,
        usage,
        response.model ?? model,
        attempts,
      );
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
      usage,
      attempts,
      raw: response,
    };
  }

  /** Modelos para os quais `reasoning.effort` é omitido (conhecidos + configurados + aprendidos em runtime). */
  supportsReasoning(model: string): boolean {
    return !this.modelsWithoutReasoning.has(model);
  }

  private request(input: TaskInput, model: string, withReasoning: boolean): Promise<ResponsesApiResponse> {
    return fetchJson<ResponsesApiResponse>(`${this.baseUrl}/responses`, {
      method: "POST",
      timeoutMs: input.timeoutMs ?? this.timeoutMs,
      maxAttempts: input.maxHttpAttempts,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model,
        input: input.prompt,
        ...(withReasoning ? { reasoning: { effort: this.reasoningEffort } } : {}),
        max_output_tokens: input.maxOutputTokens ?? this.maxOutputTokens,
      }),
    });
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
