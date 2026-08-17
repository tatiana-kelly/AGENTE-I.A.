import type { EffectLevel, ExecutionMode } from "./types.js";

export interface SecurityContext {
  mode: ExecutionMode;
  dryRun: boolean;
}

export interface SecurityDecision {
  mode: ExecutionMode;
  dryRun: boolean;
  effectLevel: EffectLevel;
  allowed: boolean;
  requiresApproval: boolean;
  reason: string;
}

/**
 * FASE 7 — execution-mode gating, generalizing the whitelist/blacklist
 * pattern already proven in `ssw-relatorios/.claude/hooks/pre_tool_check.ps1`:
 * read-only always passes; write actions are hard-blocked in READ_ONLY,
 * simulated (not executed) under DRY_RUN, gated on explicit approval in
 * ASSISTED, and only run unattended in AUTONOMOUS.
 */
export function evaluateExecution(
  context: SecurityContext,
  effectLevel: EffectLevel,
  providerMayProduceExternalEffects = false,
): SecurityDecision {
  const { mode, dryRun } = context;
  const effectiveLevel = providerMayProduceExternalEffects && effectLevel === "READ" ? "EXTERNAL_ACTION" : effectLevel;

  if (effectiveLevel === "READ") {
    return {
      mode,
      dryRun,
      effectLevel: effectiveLevel,
      allowed: true,
      requiresApproval: false,
      reason: "Ação somente leitura — permitida.",
    };
  }

  if (effectiveLevel === "UNKNOWN") {
    return {
      mode,
      dryRun,
      effectLevel: effectiveLevel,
      allowed: false,
      requiresApproval: true,
      reason: "Efeito da tarefa desconhecido — execução bloqueada por segurança (fail-closed).",
    };
  }

  if (mode === "READ_ONLY") {
    return {
      mode,
      dryRun,
      effectLevel: effectiveLevel,
      allowed: false,
      requiresApproval: false,
      reason: "Modo READ_ONLY: ações de escrita não são executadas.",
    };
  }

  if (dryRun) {
    return {
      mode,
      dryRun,
      effectLevel: effectiveLevel,
      allowed: false,
      requiresApproval: false,
      reason: "DRY_RUN ativo — ação de escrita simulada, não executada de fato.",
    };
  }

  if (mode === "ASSISTED") {
    return {
      mode,
      dryRun,
      effectLevel: effectiveLevel,
      allowed: false,
      requiresApproval: true,
      reason: "Modo ASSISTED: ação de escrita requer aprovação explícita antes de executar.",
    };
  }

  return {
    mode,
    dryRun,
    effectLevel: effectiveLevel,
    allowed: true,
    requiresApproval: false,
    reason: "Modo AUTONOMOUS: ação de escrita autorizada sem aprovação adicional.",
  };
}

/** Default is always READ_ONLY + DRY_RUN=true, even if the env var is malformed or unset. */
export function loadExecutionModeFromEnv(env: NodeJS.ProcessEnv = process.env): SecurityContext {
  const rawMode = env.ORCHESTRATOR_MODE;
  const mode: ExecutionMode = rawMode === "ASSISTED" || rawMode === "AUTONOMOUS" ? rawMode : "READ_ONLY";
  const dryRun = env.DRY_RUN !== "false";
  return { mode, dryRun };
}
