import type { ProviderName } from "../providers/types.js";
import type { ProjectManifest } from "../projects/manifest.js";
import type {
  ClassificationResult,
  EvidenceRecord,
  ExecutionMode,
  OrchestrationRequest,
  RoutingDecision,
  TaskPlan,
  ValidationStatus,
} from "../orchestrator/types.js";

export type TaskPersistenceStatus =
  | "received"
  | "running"
  | "completed"
  | "awaiting_approval"
  | "blocked"
  | "failed";

export type RunPersistenceStatus = "running" | "success" | "error" | "skipped" | "blocked";

export interface PersistedValidation {
  reviewed: boolean;
  status: ValidationStatus;
  reviewer?: ProviderName;
  summary: string;
}

export interface PersistedApproval {
  approved: true;
  source: "n8n" | "api";
  approvedAt: string;
  approvedMaxCostUsd: number;
}

export interface OrchestrationTaskRecord {
  id: string;
  request: OrchestrationRequest;
  continuedFromTaskId?: string;
  approval?: PersistedApproval;
  status: TaskPersistenceStatus;
  classification: ClassificationResult;
  routing: RoutingDecision;
  plan: TaskPlan;
  executionMode: ExecutionMode;
  dryRun: boolean;
  requiresApproval: boolean;
  validation?: PersistedValidation;
  createdAt: string;
  updatedAt: string;
}

export interface OrchestrationTaskUpdate {
  status?: TaskPersistenceStatus;
  requiresApproval?: boolean;
  validation?: PersistedValidation;
  updatedAt: string;
}

export interface OrchestrationRunRecord {
  id: string;
  taskId: string;
  stepIndex: number;
  provider: ProviderName;
  fallbackFor?: ProviderName;
  purpose: string;
  status: RunPersistenceStatus;
  output?: string;
  reason?: string;
  startedAt: string;
  completedAt?: string;
}

export interface OrchestrationRunUpdate {
  status: Exclude<RunPersistenceStatus, "running">;
  output?: string;
  reason?: string;
  completedAt: string;
}

export interface PersistedTaskSnapshot {
  task: OrchestrationTaskRecord;
  runs: OrchestrationRunRecord[];
  evidence: EvidenceRecord[];
}

export interface ProjectRecord {
  id: string;
  name: string;
  repository: string;
  defaultBranch: string;
  manifest: ProjectManifest;
  contextFiles: Record<string, string>;
  missingContextFiles: string[];
  contextSha256: string;
  active: boolean;
  updatedAt: string;
}

export type ProjectPrincipalType = "user" | "service" | "agent";
export type ProjectCapability = "read_context" | "audit" | "execute_assisted" | "approve" | "admin";

export interface ProjectPermissionRecord {
  projectId: string;
  principalType: ProjectPrincipalType;
  principalId: string;
  capability: ProjectCapability;
  createdAt: string;
}

/** Persistence boundary owned exclusively by the AI Orchestrator. */
export interface OrchestrationRepository {
  createTask(task: OrchestrationTaskRecord): Promise<void>;
  updateTask(taskId: string, update: OrchestrationTaskUpdate): Promise<void>;
  /** Atomically moves an awaiting task to running; false prevents duplicate approval replay. */
  claimTaskForContinuation(taskId: string, updatedAt: string): Promise<boolean>;
  createRun(run: OrchestrationRunRecord): Promise<void>;
  updateRun(runId: string, update: OrchestrationRunUpdate): Promise<void>;
  record(evidence: EvidenceRecord): Promise<void>;
  getTask(taskId: string): Promise<PersistedTaskSnapshot | undefined>;
  findReusableTaskByEvidenceSource(source: string, newerThan: string): Promise<PersistedTaskSnapshot | undefined>;
  upsertProject(project: ProjectRecord): Promise<void>;
  getProject(projectId: string): Promise<ProjectRecord | undefined>;
  listProjects(): Promise<ProjectRecord[]>;
  upsertProjectPermission(permission: ProjectPermissionRecord): Promise<void>;
  listProjectPermissions(projectId: string): Promise<ProjectPermissionRecord[]>;
}
