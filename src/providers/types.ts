/**
 * Provider abstraction (FASE 2). The Router never depends on a concrete
 * provider — everything talks to this interface.
 */

export type ProviderName = "openai" | "manus" | "anthropic" | "gemini";

export interface TaskInput {
  taskId: string;
  prompt: string;
  project?: string;
  context?: Record<string, unknown>;
  skill?: string;
}

export interface TaskResult {
  output: string;
  sources: string[];
  evidence: string[];
  /** 0..1. Only set when the provider itself reports a confidence signal. */
  confidence?: number;
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
