import type { EvidenceRecord } from "../orchestrator/types.js";
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

export class InMemoryOrchestrationRepository implements OrchestrationRepository {
  private readonly tasks = new Map<string, OrchestrationTaskRecord>();
  private readonly runs = new Map<string, OrchestrationRunRecord>();
  private readonly evidence: EvidenceRecord[] = [];
  private readonly projects = new Map<string, ProjectRecord>();
  private readonly projectPermissions = new Map<string, ProjectPermissionRecord>();
  private readonly oauthGrants = new Map<string, { expiresAt: string; consumedAt?: string }>();

  async createOAuthGrant(grantId: string, expiresAt: string): Promise<void> {
    if (this.oauthGrants.has(grantId)) throw new Error("OAuth grant já existe.");
    this.oauthGrants.set(grantId, { expiresAt });
  }

  async consumeOAuthGrant(grantId: string, consumedAt: string): Promise<boolean> {
    const grant = this.oauthGrants.get(grantId);
    if (!grant || grant.consumedAt || grant.expiresAt <= consumedAt) return false;
    this.oauthGrants.set(grantId, { ...grant, consumedAt });
    return true;
  }

  async createTask(task: OrchestrationTaskRecord): Promise<void> {
    if (this.tasks.has(task.id)) throw new Error(`Task ${task.id} já existe.`);
    this.tasks.set(task.id, structuredClone(task));
  }

  async updateTask(taskId: string, update: OrchestrationTaskUpdate): Promise<void> {
    const current = this.tasks.get(taskId);
    if (!current) throw new Error(`Task ${taskId} não encontrada.`);
    this.tasks.set(taskId, structuredClone({ ...current, ...update }));
  }

  async claimTaskForContinuation(taskId: string, updatedAt: string): Promise<boolean> {
    const current = this.tasks.get(taskId);
    if (!current || current.status !== "awaiting_approval") return false;
    this.tasks.set(taskId, structuredClone({ ...current, status: "running", updatedAt }));
    return true;
  }

  async createRun(run: OrchestrationRunRecord): Promise<void> {
    if (!this.tasks.has(run.taskId)) throw new Error(`Task ${run.taskId} não encontrada.`);
    if (this.runs.has(run.id)) throw new Error(`Run ${run.id} já existe.`);
    this.runs.set(run.id, structuredClone(run));
  }

  async updateRun(runId: string, update: OrchestrationRunUpdate): Promise<void> {
    const current = this.runs.get(runId);
    if (!current) throw new Error(`Run ${runId} não encontrada.`);
    this.runs.set(runId, structuredClone({ ...current, ...update }));
  }

  async record(evidence: EvidenceRecord): Promise<void> {
    if (!this.tasks.has(evidence.task_id)) throw new Error(`Task ${evidence.task_id} não encontrada.`);
    this.evidence.push(structuredClone(evidence));
  }

  async getTask(taskId: string): Promise<PersistedTaskSnapshot | undefined> {
    const task = this.tasks.get(taskId);
    if (!task) return undefined;
    return structuredClone({
      task,
      runs: [...this.runs.values()].filter((run) => run.taskId === taskId),
      evidence: this.evidence.filter((record) => record.task_id === taskId),
    });
  }

  async findReusableTaskByEvidenceSource(source: string, newerThan: string): Promise<PersistedTaskSnapshot | undefined> {
    const match = this.evidence
      .filter((record) => record.status === "success" && record.timestamp >= newerThan && record.sources.includes(source))
      .filter((record) => this.tasks.get(record.task_id)?.status === "completed")
      .sort((left, right) => right.timestamp.localeCompare(left.timestamp))[0];
    return match ? this.getTask(match.task_id) : undefined;
  }

  async upsertProject(project: ProjectRecord): Promise<void> {
    this.projects.set(project.id, structuredClone(project));
  }

  async getProject(projectId: string): Promise<ProjectRecord | undefined> {
    const project = this.projects.get(projectId);
    return project ? structuredClone(project) : undefined;
  }

  async listProjects(): Promise<ProjectRecord[]> {
    return structuredClone([...this.projects.values()].sort((left, right) => left.id.localeCompare(right.id)));
  }

  async upsertProjectPermission(permission: ProjectPermissionRecord): Promise<void> {
    this.projectPermissions.set(permissionKey(permission), structuredClone(permission));
  }

  async listProjectPermissions(projectId: string): Promise<ProjectPermissionRecord[]> {
    return structuredClone(
      [...this.projectPermissions.values()].filter((permission) => permission.projectId === projectId),
    );
  }
}

function permissionKey(permission: ProjectPermissionRecord): string {
  return [permission.projectId, permission.principalType, permission.principalId, permission.capability].join(":");
}
