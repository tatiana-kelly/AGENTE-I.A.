import type { ModelProfile, ProviderName } from "../providers/types.js";
import type { ResolvedContext } from "./contextResolver.js";

/** FASE 6 skill catalog. */
export type SkillCategory =
  | "business-analysis"
  | "data-analysis"
  | "research"
  | "architecture"
  | "programming"
  | "debugging"
  | "presentation"
  | "automation"
  | "financial-analysis"
  | "operational-analysis";

/** FASE 7. Default is always READ_ONLY. */
export type ExecutionMode = "READ_ONLY" | "ASSISTED" | "AUTONOMOUS";

/**
 * Side-effect intent inferred before any provider call. UNKNOWN is deliberately
 * fail-closed: an unclassified task must not be treated as read-only.
 */
export type EffectLevel = "READ" | "WRITE" | "EXTERNAL_ACTION" | "UNKNOWN";

/** FASE 4. */
export type AgentMode = "ONE_AGENT" | "MULTI_AGENT";

export type ValidationStatus = "APPROVED" | "REJECTED" | "NEEDS_HUMAN";
export type EvidenceStatus = "success" | "error" | "skipped" | "blocked";

export interface ClassificationResult {
  skills: SkillCategory[];
  effectLevel: EffectLevel;
  requiresGoogleWorkspace: boolean;
  requiresInvestigation: boolean;
  requiresImplementation: boolean;
  requiresDecision: boolean;
  requiresAdversarialReview: boolean;
  /** Short justification only — never chain-of-thought (FASE 8). */
  rationale: string;
}

export interface RoutingDecision {
  primary: ProviderName;
  reviewer?: ProviderName;
  reason: string;
  /** 0..1 heuristic score derived from how many rules matched, not invented. */
  confidence: number;
  fallback?: ProviderName;
}

export interface PlanStep {
  provider: ProviderName;
  purpose: string;
  modelProfile?: ModelProfile;
}

export interface TaskPlan {
  mode: AgentMode;
  steps: PlanStep[];
}

/** FASE 8 — Evidence-First. Structured fields only, no private chain-of-thought. */
export interface EvidenceRecord {
  task_id: string;
  run_id?: string;
  project?: string;
  provider: ProviderName;
  model?: string;
  skill?: SkillCategory;
  routing_reason: string;
  sources: string[];
  evidence: string[];
  result: string;
  status: EvidenceStatus;
  reason?: string;
  confidence: number;
  timestamp: string;
  limitations?: string;
  fallback_triggered?: boolean;
  fallback_reason?: string;
}

export interface OrchestrationRequest {
  task: string;
  project?: string;
}

export type StepStatus = "success" | "error" | "skipped";

export interface StepExecutionResult {
  provider: ProviderName;
  /** Original provider replaced by this provider after a controlled failure. */
  fallbackFor?: ProviderName;
  purpose: string;
  status: StepStatus;
  /** Só presente quando status === "success". */
  output?: string;
  /** Motivo do skip/erro — nunca lançado sem ser reportado (FASE 10). */
  reason?: string;
}

export interface OrchestrationResult {
  taskId: string;
  classification: ClassificationResult;
  context: ResolvedContext;
  routing: RoutingDecision;
  plan: TaskPlan;
  executionMode: ExecutionMode;
  dryRun: boolean;
  requiresApproval: boolean;
  /** Vazio quando o gate de segurança bloqueou a execução (ver `requiresApproval`). */
  results: StepExecutionResult[];
  evidence: EvidenceRecord[];
  validation?: {
    reviewed: boolean;
    status: ValidationStatus;
    reviewer?: ProviderName;
    summary: string;
    reviewOutput?: string;
  };
}
