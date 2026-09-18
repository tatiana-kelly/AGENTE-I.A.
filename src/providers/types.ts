/**
 * Provider abstraction (FASE 2). The Router never depends on a concrete
 * provider — everything talks to this interface.
 */

export type ProviderName = "openai" | "manus" | "anthropic" | "gemini";
export type ModelProfile = "fast" | "balanced" | "critical" | "adversarial" | "builder";

export interface TaskInput {
  taskId: string;
  prompt: string;
  project?: string;
  context?: Record<string, unknown>;
  skill?: string;
  modelProfile?: ModelProfile;
  /**
   * Tempo limite DESTA chamada, em ms. Opcional: quando ausente, vale o timeout configurado do provider
   * (padrão do httpClient: 30 s) — comportamento idêntico ao anterior para quem não informa (/orchestrate).
   */
  timeoutMs?: number;
  /**
   * Limite de tokens de saída DESTA chamada. Opcional: quando ausente, vale o limite configurado do
   * provider (ANTHROPIC_MAX_OUTPUT_TOKENS / OPENAI_MAX_OUTPUT_TOKENS) — igual ao comportamento anterior.
   */
  maxOutputTokens?: number;
  /**
   * Máximo de requisições HTTP desta chamada (retentativas automáticas do httpClient incluídas).
   * Opcional: ausente = padrão do httpClient (3). O agent-run usa 1 para que NENHUMA tentativa cobrável
   * aconteça sem passar pelo portão de custo e sem aparecer no uso registrado.
   */
  maxHttpAttempts?: number;
}

/** Tokens medidos, reportados pela própria API do provider — nunca estimados aqui. */
export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

export interface TaskResult {
  output: string;
  model?: string;
  sources: string[];
  evidence: string[];
  /** 0..1. Only set when the provider itself reports a confidence signal. */
  confidence?: number;
  /** Só presente quando a resposta da API traz a métrica de uso — ausente ≠ zero. */
  usage?: TokenUsage;
  /** Requisições HTTP feitas pelo provider nesta chamada (ex.: 2 quando adaptou um parâmetro recusado). */
  attempts?: number;
  raw?: unknown;
}

export interface HealthStatus {
  healthy: boolean;
  latencyMs?: number;
  message?: string;
  checkedAt: string;
}

export interface ProviderCapabilities {
  /** True when the provider can invoke remote tools or affect external systems. */
  mayProduceExternalEffects: boolean;
  /** Conservative maximum reserved before each call. Undefined is fail-closed. */
  estimatedMaxCostUsd?: number;
}

export interface AIProvider {
  readonly name: ProviderName;
  readonly capabilities: ProviderCapabilities;
  analyze(input: TaskInput): Promise<TaskResult>;
  healthCheck(): Promise<HealthStatus>;
}
