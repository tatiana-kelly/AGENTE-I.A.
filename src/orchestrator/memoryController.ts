import { createHash } from "node:crypto";
import type { OrchestrationRepository, PersistedTaskSnapshot } from "../persistence/index.js";
import type { ClassificationResult, OrchestrationRequest, TaskPlan } from "./types.js";
import type { ResolvedContext } from "./contextResolver.js";

const MEMORY_SCHEMA_VERSION = 1;
const DEFAULT_MAX_AGE_HOURS = 24 * 7;

export interface ResultMemoryConfig {
  enabled: boolean;
  maxAgeHours: number;
}

export interface MemoryLookupResult {
  key: string;
  source: string;
  snapshot?: PersistedTaskSnapshot;
  reason: string;
}

export function loadResultMemoryConfigFromEnv(env: NodeJS.ProcessEnv = process.env): ResultMemoryConfig {
  return {
    enabled: env.RESULT_MEMORY_ENABLED?.trim().toLowerCase() !== "false",
    maxAgeHours: nonNegativeNumberOrDefault(env.RESULT_MEMORY_MAX_AGE_HOURS, DEFAULT_MAX_AGE_HOURS),
  };
}

export function buildResultMemoryKey(input: {
  request: OrchestrationRequest;
  context: ResolvedContext;
  classification: ClassificationResult;
  plan: TaskPlan;
}): string {
  const canonical = JSON.stringify({
    version: MEMORY_SCHEMA_VERSION,
    task: normalizeTask(input.request.task),
    project: input.request.project ?? null,
    context: Object.entries(input.context.loaded).sort(([left], [right]) => left.localeCompare(right)),
    missingContext: [...input.context.missing].sort(),
    classification: input.classification,
    plan: input.plan,
  });
  return createHash("sha256").update(canonical).digest("hex");
}

export function resultMemorySource(key: string): string {
  return `sal-memory://v${MEMORY_SCHEMA_VERSION}/${key}`;
}

export async function lookupReusableResult(
  repository: OrchestrationRepository | undefined,
  request: OrchestrationRequest,
  classification: ClassificationResult,
  key: string,
  config: ResultMemoryConfig,
  now = new Date(),
): Promise<MemoryLookupResult> {
  const source = resultMemorySource(key);
  if (!config.enabled) return { key, source, reason: "Memória de resultados desabilitada." };
  if (!repository) return { key, source, reason: "Persistência indisponível para consultar memória." };
  if (request.reusePolicy === "refresh") return { key, source, reason: "Reanálise forçada pelo solicitante." };
  if (classification.effectLevel !== "READ") {
    return { key, source, reason: "Somente resultados de leitura podem ser reutilizados." };
  }

  const newerThan = new Date(now.getTime() - config.maxAgeHours * 60 * 60 * 1_000).toISOString();
  const snapshot = await repository.findReusableTaskByEvidenceSource(source, newerThan);
  if (!snapshot) return { key, source, reason: "Nenhum resultado válido e vigente encontrado." };
  if (snapshot.task.validation?.status !== "APPROVED") {
    return { key, source, reason: "Resultado anterior não possui validação aprovada." };
  }
  return { key, source, snapshot, reason: "Resultado aprovado reutilizado sem nova chamada de IA." };
}

export function reusableArtifact(snapshot: PersistedTaskSnapshot) {
  const finalStepIndex = Math.max(0, snapshot.task.plan.steps.length - 1);
  const run = [...snapshot.runs]
    .filter((candidate) => candidate.status === "success" && candidate.stepIndex === finalStepIndex && candidate.output)
    .sort((left, right) => right.startedAt.localeCompare(left.startedAt))[0];
  if (!run?.output) return undefined;
  const evidence = snapshot.evidence.find((record) => record.run_id === run.id && record.status === "success");
  return { run, evidence };
}

function normalizeTask(task: string): string {
  return task.trim().replace(/\s+/g, " ");
}

function nonNegativeNumberOrDefault(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}
