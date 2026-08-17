import type { ProviderName, TaskResult } from "../providers/types.js";
import type { EvidenceRecord, EvidenceStatus, SkillCategory } from "./types.js";

/**
 * FASE 8 — Evidence-First. Sink is pluggable so FASE 11 can add a Supabase
 * implementation (see `pendency-tracker`'s `integration_action_audit` /
 * `integration_ingestion_audit` tables for prior art) without changing
 * anything upstream of this interface.
 */
export interface EvidenceSink {
  record(evidence: EvidenceRecord): Promise<void>;
}

export class InMemoryEvidenceSink implements EvidenceSink {
  private readonly records: EvidenceRecord[] = [];

  async record(evidence: EvidenceRecord): Promise<void> {
    this.records.push(evidence);
  }

  list(): readonly EvidenceRecord[] {
    return this.records;
  }
}

export interface BuildEvidenceParams {
  taskId: string;
  project?: string;
  provider: ProviderName;
  model?: string;
  skill?: SkillCategory;
  routingReason: string;
  result: TaskResult;
  status?: EvidenceStatus;
  reason?: string;
  confidence: number;
  timestamp: string;
  limitations?: string;
  fallbackTriggered?: boolean;
  fallbackReason?: string;
}

/**
 * Builds the structured evidence record. Deliberately excludes anything
 * resembling private chain-of-thought — only the summary fields FASE 8
 * allows (justificativa resumida, evidências, decisão, resultado, confiança,
 * limitações) ever go in.
 */
export function buildEvidenceRecord(params: BuildEvidenceParams): EvidenceRecord {
  return {
    task_id: params.taskId,
    project: params.project,
    provider: params.provider,
    model: params.model,
    skill: params.skill,
    routing_reason: params.routingReason,
    sources: params.result.sources,
    evidence: params.result.evidence,
    result: params.result.output,
    status: params.status ?? "success",
    reason: params.reason,
    confidence: params.confidence,
    timestamp: params.timestamp,
    limitations: params.limitations,
    fallback_triggered: params.fallbackTriggered,
    fallback_reason: params.fallbackReason,
  };
}
