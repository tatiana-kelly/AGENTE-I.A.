import type { ProviderName } from "../providers/types.js";
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

export interface OrchestrationTaskRecord {
  id: string;
  request: OrchestrationRequest;
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

/** Persistence boundary owned exclusively by the AI Orchestrator. */
export interface OrchestrationRepository {
  createTask(task: OrchestrationTaskRecord): Promise<void>;
  updateTask(taskId: string, update: OrchestrationTaskUpdate): Promise<void>;
  createRun(run: OrchestrationRunRecord): Promise<void>;
  updateRun(runId: string, update: OrchestrationRunUpdate): Promise<void>;
  record(evidence: EvidenceRecord): Promise<void>;
  getTask(taskId: string): Promise<PersistedTaskSnapshot | undefined>;
}
