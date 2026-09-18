/**
 * Persistência durável do agent-run no Supabase do Orchestrator (mesmo padrão REST de
 * persistence/supabase.ts). Guarda só o mínimo: idempotência e auditoria técnica.
 *
 * Requer a migration supabase/migrations/202609170001_create_agent_runs.sql — NÃO aplicada ainda.
 * Sem as tabelas, a rota continua funcionando com o store em memória (idempotência só no processo).
 */

import { z } from "zod";
import type { AgentRunResponse } from "./contract.js";
import type { AgentRunAuditRecord, AgentRunStore, StoredAgentRun } from "./store.js";

type FetchLike = typeof fetch;

export interface SupabaseAgentRunStoreConfig {
  url: string;
  serviceRoleKey: string;
  fetchImpl?: FetchLike;
}

const runRowSchema = z.object({
  idempotency_key_hash: z.string(),
  request_hash: z.string(),
  response: z.unknown(),
  created_at: z.string(),
  expires_at: z.string(),
});

export class SupabaseAgentRunStore implements AgentRunStore {
  private readonly baseUrl: string;
  private readonly serviceRoleKey: string;
  private readonly fetchImpl: FetchLike;

  constructor(config: SupabaseAgentRunStoreConfig) {
    const parsed = new URL(config.url);
    if (parsed.protocol !== "https:" && parsed.hostname !== "localhost" && parsed.hostname !== "127.0.0.1") {
      throw new Error("SUPABASE_URL deve usar HTTPS (exceto ambiente local).");
    }
    if (!config.serviceRoleKey.trim()) throw new Error("SUPABASE_SERVICE_ROLE_KEY não configurada.");
    this.baseUrl = parsed.toString().replace(/\/$/, "");
    this.serviceRoleKey = config.serviceRoleKey;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  async find(idempotencyKeyHash: string, now: Date): Promise<StoredAgentRun | undefined> {
    const response = await this.request(
      `ai_agent_runs?idempotency_key_hash=eq.${encodeURIComponent(idempotencyKeyHash)}` +
        `&expires_at=gt.${encodeURIComponent(now.toISOString())}&select=*`,
      { method: "GET", headers: { Prefer: "return=representation" } },
    );
    const rows = z.array(runRowSchema).parse(await response.json());
    const row = rows[0];
    if (!row) return undefined;
    return {
      idempotencyKeyHash: row.idempotency_key_hash,
      requestHash: row.request_hash,
      response: row.response as AgentRunResponse,
      createdAt: row.created_at,
      expiresAt: row.expires_at,
    };
  }

  async save(run: StoredAgentRun): Promise<void> {
    await this.request("ai_agent_runs", {
      method: "POST",
      headers: { Prefer: "resolution=merge-duplicates,return=minimal" },
      body: JSON.stringify({
        idempotency_key_hash: run.idempotencyKeyHash,
        request_hash: run.requestHash,
        response: run.response,
        created_at: run.createdAt,
        expires_at: run.expiresAt,
      }),
    });
  }

  async audit(record: AgentRunAuditRecord): Promise<void> {
    await this.request("ai_agent_run_audit", { method: "POST", body: JSON.stringify(record) });
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const response = await this.fetchImpl(`${this.baseUrl}/rest/v1/${path}`, {
      ...init,
      headers: {
        apikey: this.serviceRoleKey,
        Authorization: `Bearer ${this.serviceRoleKey}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
        ...init.headers,
      },
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 1_000);
      throw new Error(`Supabase ${init.method ?? "GET"} ${path} falhou (${response.status}): ${detail}`);
    }
    return response;
  }
}

export function buildAgentRunStoreFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  fetchImpl?: FetchLike,
): SupabaseAgentRunStore | undefined {
  const url = env.SUPABASE_URL?.trim();
  const serviceRoleKey = env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!url || !serviceRoleKey) return undefined;
  return new SupabaseAgentRunStore({ url, serviceRoleKey, fetchImpl });
}
