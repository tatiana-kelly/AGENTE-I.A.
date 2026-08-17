import { z } from "zod";
import type { EvidenceRecord } from "../orchestrator/types.js";
import type {
  OrchestrationRepository,
  OrchestrationRunRecord,
  OrchestrationRunUpdate,
  OrchestrationTaskRecord,
  OrchestrationTaskUpdate,
  PersistedTaskSnapshot,
} from "./types.js";

type FetchLike = typeof fetch;

export interface SupabaseRepositoryConfig {
  url: string;
  serviceRoleKey: string;
  fetchImpl?: FetchLike;
}

const taskRowSchema = z.object({
  id: z.string().uuid(),
  task_text: z.string(),
  project: z.string().nullable(),
  status: z.enum(["received", "running", "completed", "awaiting_approval", "blocked", "failed"]),
  classification: z.unknown(),
  routing: z.unknown(),
  plan: z.unknown(),
  execution_mode: z.enum(["READ_ONLY", "ASSISTED", "AUTONOMOUS"]),
  dry_run: z.boolean(),
  requires_approval: z.boolean(),
  validation: z.unknown().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

const runRowSchema = z.object({
  id: z.string().uuid(),
  task_id: z.string().uuid(),
  step_index: z.number().int().nonnegative(),
  provider: z.enum(["openai", "manus", "anthropic", "gemini"]),
  fallback_for: z.enum(["openai", "manus", "anthropic", "gemini"]).nullable(),
  purpose: z.string(),
  status: z.enum(["running", "success", "error", "skipped", "blocked"]),
  output: z.string().nullable(),
  reason: z.string().nullable(),
  started_at: z.string(),
  completed_at: z.string().nullable(),
});

const evidenceRowSchema = z.object({
  task_id: z.string().uuid(),
  run_id: z.string().uuid().nullable(),
  project: z.string().nullable(),
  provider: z.enum(["openai", "manus", "anthropic", "gemini"]),
  model: z.string().nullable(),
  skill: z.string().nullable(),
  routing_reason: z.string(),
  sources: z.array(z.string()),
  evidence: z.array(z.string()),
  result: z.string(),
  status: z.enum(["success", "error", "skipped", "blocked"]),
  reason: z.string().nullable(),
  confidence: z.number(),
  recorded_at: z.string(),
  limitations: z.string().nullable(),
  fallback_triggered: z.boolean(),
  fallback_reason: z.string().nullable(),
});

export class SupabaseOrchestrationRepository implements OrchestrationRepository {
  private readonly baseUrl: string;
  private readonly serviceRoleKey: string;
  private readonly fetchImpl: FetchLike;

  constructor(config: SupabaseRepositoryConfig) {
    const parsedUrl = new URL(config.url);
    if (parsedUrl.protocol !== "https:" && parsedUrl.hostname !== "localhost" && parsedUrl.hostname !== "127.0.0.1") {
      throw new Error("SUPABASE_URL deve usar HTTPS (exceto ambiente local)." );
    }
    if (!config.serviceRoleKey.trim()) throw new Error("SUPABASE_SERVICE_ROLE_KEY não configurada.");
    this.baseUrl = parsedUrl.toString().replace(/\/$/, "");
    this.serviceRoleKey = config.serviceRoleKey;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  async createTask(task: OrchestrationTaskRecord): Promise<void> {
    await this.request("ai_tasks", { method: "POST", body: JSON.stringify(toTaskRow(task)) });
  }

  async updateTask(taskId: string, update: OrchestrationTaskUpdate): Promise<void> {
    await this.request(`ai_tasks?id=eq.${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      body: JSON.stringify(toTaskUpdateRow(update)),
    });
  }

  async createRun(run: OrchestrationRunRecord): Promise<void> {
    await this.request("ai_runs", { method: "POST", body: JSON.stringify(toRunRow(run)) });
  }

  async updateRun(runId: string, update: OrchestrationRunUpdate): Promise<void> {
    await this.request(`ai_runs?id=eq.${encodeURIComponent(runId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: update.status,
        output: update.output,
        reason: update.reason,
        completed_at: update.completedAt,
      }),
    });
  }

  async record(evidence: EvidenceRecord): Promise<void> {
    await this.request("ai_evidence", { method: "POST", body: JSON.stringify(toEvidenceRow(evidence)) });
  }

  async getTask(taskId: string): Promise<PersistedTaskSnapshot | undefined> {
    const queryId = encodeURIComponent(taskId);
    const [taskRows, runRows, evidenceRows] = await Promise.all([
      this.requestJson(`ai_tasks?id=eq.${queryId}&select=*`),
      this.requestJson(`ai_runs?task_id=eq.${queryId}&select=*&order=step_index.asc,started_at.asc`),
      this.requestJson(`ai_evidence?task_id=eq.${queryId}&select=*&order=recorded_at.asc`),
    ]);
    const tasks = z.array(taskRowSchema).parse(taskRows);
    if (!tasks[0]) return undefined;
    return {
      task: fromTaskRow(tasks[0]),
      runs: z.array(runRowSchema).parse(runRows).map(fromRunRow),
      evidence: z.array(evidenceRowSchema).parse(evidenceRows).map(fromEvidenceRow),
    };
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

  private async requestJson(path: string): Promise<unknown> {
    const response = await this.request(path, { method: "GET", headers: { Prefer: "return=representation" } });
    return response.json();
  }
}

export function buildSupabaseRepositoryFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  fetchImpl?: FetchLike,
): SupabaseOrchestrationRepository | undefined {
  const url = env.SUPABASE_URL?.trim();
  const serviceRoleKey = env.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!url && !serviceRoleKey) return undefined;
  if (!url || !serviceRoleKey) throw new Error("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY devem ser configuradas juntas.");
  return new SupabaseOrchestrationRepository({ url, serviceRoleKey, fetchImpl });
}

function toTaskRow(task: OrchestrationTaskRecord): Record<string, unknown> {
  return {
    id: task.id,
    task_text: task.request.task,
    project: task.request.project,
    status: task.status,
    classification: task.classification,
    routing: task.routing,
    plan: task.plan,
    execution_mode: task.executionMode,
    dry_run: task.dryRun,
    requires_approval: task.requiresApproval,
    validation: task.validation,
    created_at: task.createdAt,
    updated_at: task.updatedAt,
  };
}

function toTaskUpdateRow(update: OrchestrationTaskUpdate): Record<string, unknown> {
  return {
    status: update.status,
    requires_approval: update.requiresApproval,
    validation: update.validation,
    updated_at: update.updatedAt,
  };
}

function toRunRow(run: OrchestrationRunRecord): Record<string, unknown> {
  return {
    id: run.id,
    task_id: run.taskId,
    step_index: run.stepIndex,
    provider: run.provider,
    fallback_for: run.fallbackFor,
    purpose: run.purpose,
    status: run.status,
    output: run.output,
    reason: run.reason,
    started_at: run.startedAt,
    completed_at: run.completedAt,
  };
}

function toEvidenceRow(record: EvidenceRecord): Record<string, unknown> {
  return {
    task_id: record.task_id,
    run_id: record.run_id,
    project: record.project,
    provider: record.provider,
    model: record.model,
    skill: record.skill,
    routing_reason: record.routing_reason,
    sources: record.sources,
    evidence: record.evidence,
    result: record.result,
    status: record.status,
    reason: record.reason,
    confidence: record.confidence,
    recorded_at: record.timestamp,
    limitations: record.limitations,
    fallback_triggered: record.fallback_triggered ?? false,
    fallback_reason: record.fallback_reason,
  };
}

function fromTaskRow(row: z.infer<typeof taskRowSchema>): OrchestrationTaskRecord {
  return {
    id: row.id,
    request: { task: row.task_text, project: row.project ?? undefined },
    status: row.status,
    classification: row.classification as OrchestrationTaskRecord["classification"],
    routing: row.routing as OrchestrationTaskRecord["routing"],
    plan: row.plan as OrchestrationTaskRecord["plan"],
    executionMode: row.execution_mode,
    dryRun: row.dry_run,
    requiresApproval: row.requires_approval,
    validation: (row.validation ?? undefined) as OrchestrationTaskRecord["validation"],
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function fromRunRow(row: z.infer<typeof runRowSchema>): OrchestrationRunRecord {
  return {
    id: row.id,
    taskId: row.task_id,
    stepIndex: row.step_index,
    provider: row.provider,
    fallbackFor: row.fallback_for ?? undefined,
    purpose: row.purpose,
    status: row.status,
    output: row.output ?? undefined,
    reason: row.reason ?? undefined,
    startedAt: row.started_at,
    completedAt: row.completed_at ?? undefined,
  };
}

function fromEvidenceRow(row: z.infer<typeof evidenceRowSchema>): EvidenceRecord {
  return {
    task_id: row.task_id,
    run_id: row.run_id ?? undefined,
    project: row.project ?? undefined,
    provider: row.provider,
    model: row.model ?? undefined,
    skill: row.skill as EvidenceRecord["skill"],
    routing_reason: row.routing_reason,
    sources: row.sources,
    evidence: row.evidence,
    result: row.result,
    status: row.status,
    reason: row.reason ?? undefined,
    confidence: row.confidence,
    timestamp: row.recorded_at,
    limitations: row.limitations ?? undefined,
    fallback_triggered: row.fallback_triggered,
    fallback_reason: row.fallback_reason ?? undefined,
  };
}
