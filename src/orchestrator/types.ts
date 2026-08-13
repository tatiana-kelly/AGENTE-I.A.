import type { ProviderName } from "../providers/types.js";
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

/** FASE 4. */
export type AgentMode = "ONE_AGENT" | "MULTI_AGENT";

export interface ClassificationResult {
  skills: SkillCategory[];
  requiresGoogleWorkspace: boolean;
  requiresInvestigation: boolean;
  requiresImplementation: boolean;
  requiresDecision: boolean;
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
}

export interface TaskPlan {
  mode: AgentMode;
  steps: PlanStep[];
}

/** FASE 8 — Evidence-First. Structured fields only, no private chain-of-thought. */
export interface EvidenceRecord {
  task_id: string;
  project?: string;
  provider: ProviderName;
  model?: string;
  skill?: SkillCategory;
  routing_reason: string;
  sources: string[];
  evidence: string[];
  result: string;
  confidence: number;
  timestamp: string;
  limitations?: string;
  fallback_triggered?: boolean;
  fallback_reason?: string;
}

export interface OrchestrationRequest {
  task: string;
  project?: string;
  mode?: "auto" | ExecutionMode;
}

export interface OrchestrationResult {
  classification: ClassificationResult;
  context: ResolvedContext;
  routing: RoutingDecision;
  plan: TaskPlan;
  executionMode: ExecutionMode;
  dryRun: boolean;
  requiresApproval: boolean;
}
