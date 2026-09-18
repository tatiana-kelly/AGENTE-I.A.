/**
 * Persistência mínima do agent-run: idempotência (janela de 7 dias) e auditoria técnica.
 *
 * Não guarda memória empresarial — caso, decisão, ação, verificação e aprendizado continuam no SAL OS.
 * Aqui ficam apenas: chave de idempotência, hash da requisição, resposta devolvida e o registro de auditoria.
 */

import { createHash } from "node:crypto";
import type { AgentRunResponse } from "./contract.js";
import { LIMITS } from "./contract.js";

export interface AgentRunAuditRecord {
  request_id: string;
  idempotency_key_hash: string;
  principal: string;
  project: string;
  agent: string;
  agent_version: string;
  provider: string | "unknown";
  model: string | "unknown";
  attempt: number;
  status: string;
  latency_ms: number | "unknown";
  input_tokens: number | "unknown";
  output_tokens: number | "unknown";
  cost_usd: number | "unknown";
  fallback_triggered: boolean;
  review_status: string;
  validation_status: string;
  created_at: string;
}

export interface StoredAgentRun {
  idempotencyKeyHash: string;
  requestHash: string;
  response: AgentRunResponse;
  createdAt: string;
  expiresAt: string;
}

export interface AgentRunStore {
  /** Devolve o registro vivo da chave, se houver. */
  find(idempotencyKeyHash: string, now: Date): Promise<StoredAgentRun | undefined>;
  save(run: StoredAgentRun): Promise<void>;
  audit(record: AgentRunAuditRecord): Promise<void>;
}

export function hashIdempotencyKey(key: string): string {
  return createHash("sha256").update(key, "utf8").digest("hex");
}

/** Hash estável do corpo: mesma chave + corpo diferente = conflito. */
export function hashRequest(body: unknown): string {
  return createHash("sha256").update(stableStringify(body), "utf8").digest("hex");
}

export function bodyHashHex(raw: string): string {
  return createHash("sha256").update(raw, "utf8").digest("hex");
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
}

export function expiryFrom(now: Date): string {
  return new Date(now.getTime() + LIMITS.idempotencyWindowDays * 24 * 60 * 60 * 1000).toISOString();
}

export class InMemoryAgentRunStore implements AgentRunStore {
  private readonly runs = new Map<string, StoredAgentRun>();
  readonly auditLog: AgentRunAuditRecord[] = [];

  async find(idempotencyKeyHash: string, now: Date): Promise<StoredAgentRun | undefined> {
    const stored = this.runs.get(idempotencyKeyHash);
    if (!stored) return undefined;
    if (new Date(stored.expiresAt).getTime() <= now.getTime()) {
      this.runs.delete(idempotencyKeyHash);
      return undefined;
    }
    return structuredClone(stored);
  }

  async save(run: StoredAgentRun): Promise<void> {
    this.runs.set(run.idempotencyKeyHash, structuredClone(run));
  }

  async audit(record: AgentRunAuditRecord): Promise<void> {
    this.auditLog.push({ ...record });
  }
}
