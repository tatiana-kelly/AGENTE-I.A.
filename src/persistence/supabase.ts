import { z } from "zod";
import type { EvidenceRecord } from "../orchestrator/types.js";
import { projectManifestSchema } from "../projects/manifest.js";
import type {
  OrchestrationRepository,
  OrchestrationRunRecord,
  OrchestrationRunUpdate,
  OrchestrationTaskRecord,
  OrchestrationTaskUpdate,
  PersistedTaskSnapshot,
  ProjectPermissionRecord,
  ProjectRecord,
} from "./types.js";

type FetchLike = typeof fetch;

export interface SupabaseRepositoryConfig {
  url: string;
  serviceRoleKey: string;
  fetchImpl?: FetchLike;
}

const providerNameSchema = z.enum(["openai", "manus", "anthropic", "gemini"]);
const skillSchema = z.enum([
  "business-analysis",
  "data-analysis",
  "research",
  "architecture",
  "programming",
  "debugging",
  "presentation",
  "automation",
  "financial-analysis",
  "operational-analysis",
]);
const classificationSchema = z.object({
  skills: z.array(skillSchema),
  effectLevel: z.enum(["READ", "WRITE", "EXTERNAL_ACTION", "UNKNOWN"]),
  requiresGoogleWorkspace: z.boolean(),
  requiresInvestigation: z.boolean(),
  requiresImplementation: z.boolean(),
  requiresDecision: z.boolean(),
  requiresAdversarialReview: z.boolean().default(false),
  rationale: z.string(),
});
const routingSchema = z.object({
  primary: providerNameSchema,
  reviewer: providerNameSchema.optional(),
  reason: z.string(),
  confidence: z.number().min(0).max(1),
  fallback: providerNameSchema.optional(),
});
const planSchema = z.object({
  mode: z.enum(["ONE_AGENT", "MULTI_AGENT"]),
  steps: z.array(z.object({
    provider: providerNameSchema,
    purpose: z.string(),
    modelProfile: z.enum(["fast", "balanced", "critical", "adversarial", "builder"]).optional(),
  })),
});
const validationSchema = z.object({
  reviewed: z.boolean(),
  status: z.enum(["APPROVED", "REJECTED", "NEEDS_HUMAN"]),
  reviewer: providerNameSchema.optional(),
  summary: z.string(),
});
const approvalSchema = z.object({
  approved: z.literal(true),
  source: z.enum(["n8n", "api"]),
  approvedAt: z.string(),
  approvedMaxCostUsd: z.number().nonnegative(),
});

const taskRowSchema = z.object({
  id: z.string().uuid(),
  task_text: z.string(),
  project: z.string().nullable(),
  continued_from_task_id: z.string().uuid().nullable(),
  approval: approvalSchema.nullable(),
  status: z.enum(["received", "running", "completed", "awaiting_approval", "blocked", "failed"]),
  classification: classificationSchema,
  routing: routingSchema,
  plan: planSchema,
  execution_mode: z.enum(["READ_ONLY", "ASSISTED", "AUTONOMOUS"]),
  dry_run: z.boolean(),
  requires_approval: z.boolean(),
  validation: validationSchema.nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

const runRowSchema = z.object({
  id: z.string().uuid(),
  task_id: z.string().uuid(),
  step_index: z.number().int().nonnegative(),
  provider: providerNameSchema,
  fallback_for: providerNameSchema.nullable(),
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
  provider: providerNameSchema,
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

const projectRowSchema = z.object({
  id: z.string(),
  name: z.string(),
  repository: z.string(),
  default_branch: z.string(),
  manifest: z.unknown(),
  context_files: z.record(z.string()),
  missing_context_files: z.array(z.string()),
  context_sha256: z.string(),
  active: z.boolean(),
  updated_at: z.string(),
});

const permissionRowSchema = z.object({
  project_id: z.string(),
  principal_type: z.enum(["user", "service", "agent"]),
  principal_id: z.string(),
  capability: z.enum(["read_context", "audit", "execute_assisted", "approve", "admin"]),
  created_at: z.string(),
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

  async claimTaskForContinuation(taskId: string, updatedAt: string): Promise<boolean> {
    const response = await this.request(
      `ai_tasks?id=eq.${encodeURIComponent(taskId)}&status=eq.awaiting_approval&select=*`,
      {
        method: "PATCH",
        headers: { Prefer: "return=representation" },
        body: JSON.stringify({ status: "running", updated_at: updatedAt }),
      },
    );
    const rows = z.array(taskRowSchema).parse(await response.json());
    return rows.length === 1;
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

  async findReusableTaskByEvidenceSource(source: string, newerThan: string): Promise<PersistedTaskSnapshot | undefined> {
    const query = new URLSearchParams({
      status: "eq.success",
      recorded_at: `gte.${newerThan}`,
      sources: `cs.{${JSON.stringify(source)}}`,
      select: "*",
      order: "recorded_at.desc",
      limit: "20",
    });
    const rows = z.array(evidenceRowSchema).parse(await this.requestJson(`ai_evidence?${query.toString()}`));
    for (const row of rows) {
      const snapshot = await this.getTask(row.task_id);
      if (snapshot?.task.status === "completed") return snapshot;
    }
    return undefined;
  }

  async upsertProject(project: ProjectRecord): Promise<void> {
    await this.request("ai_projects?on_conflict=id", {
      method: "POST",
      headers: { Prefer: "resolution=merge-duplicates,return=minimal" },
      body: JSON.stringify(toProjectRow(project)),
    });
  }

  async getProject(projectId: string): Promise<ProjectRecord | undefined> {
    const rows = z.array(projectRowSchema).parse(
      await this.requestJson(`ai_projects?id=eq.${encodeURIComponent(projectId)}&select=*`),
    );
    return rows[0] ? fromProjectRow(rows[0]) : undefined;
  }

  async listProjects(): Promise<ProjectRecord[]> {
    const rows = z.array(projectRowSchema).parse(await this.requestJson("ai_projects?active=eq.true&select=*&order=id.asc"));
    return rows.map(fromProjectRow);
  }

  async upsertProjectPermission(permission: ProjectPermissionRecord): Promise<void> {
    await this.request("ai_project_permissions?on_conflict=project_id,principal_type,principal_id,capability", {
      method: "POST",
      headers: { Prefer: "resolution=merge-duplicates,return=minimal" },
      body: JSON.stringify({
        project_id: permission.projectId,
        principal_type: permission.principalType,
        principal_id: permission.principalId,
        capability: permission.capability,
        created_at: permission.createdAt,
      }),
    });
  }

  async listProjectPermissions(projectId: string): Promise<ProjectPermissionRecord[]> {
    const rows = z.array(permissionRowSchema).parse(
      await this.requestJson(
        `ai_project_permissions?project_id=eq.${encodeURIComponent(projectId)}&select=*&order=principal_type.asc,principal_id.asc`,
      ),
    );
    return rows.map((row) => ({
      projectId: row.project_id,
      principalType: row.principal_type,
      principalId: row.principal_id,
      capability: row.capability,
      createdAt: row.created_at,
    }));
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
    continued_from_task_id: task.continuedFromTaskId,
    approval: task.approval,
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
    continuedFromTaskId: row.continued_from_task_id ?? undefined,
    approval: row.approval ?? undefined,
    status: row.status,
    classification: row.classification,
    routing: row.routing,
    plan: row.plan,
    executionMode: row.execution_mode,
    dryRun: row.dry_run,
    requiresApproval: row.requires_approval,
    validation: row.validation ?? undefined,
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

function toProjectRow(project: ProjectRecord): Record<string, unknown> {
  return {
    id: project.id,
    name: project.name,
    repository: project.repository,
    default_branch: project.defaultBranch,
    manifest: project.manifest,
    context_files: project.contextFiles,
    missing_context_files: project.missingContextFiles,
    context_sha256: project.contextSha256,
    active: project.active,
    updated_at: project.updatedAt,
  };
}

function fromProjectRow(row: z.infer<typeof projectRowSchema>): ProjectRecord {
  return {
    id: row.id,
    name: row.name,
    repository: row.repository,
    defaultBranch: row.default_branch,
    manifest: projectManifestSchema.parse(row.manifest),
    contextFiles: row.context_files,
    missingContextFiles: row.missing_context_files,
    contextSha256: row.context_sha256,
    active: row.active,
    updatedAt: row.updated_at,
  };
}
