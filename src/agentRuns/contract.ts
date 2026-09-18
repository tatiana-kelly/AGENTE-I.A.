/**
 * Contrato sal.agent-run/1.0 — superfície oficial SAL Intelligence OS → AI Orchestrator.
 *
 * Schema fechado (`.strict()` em todos os níveis): propriedade desconhecida é erro 400, nunca ignorada.
 * Os limites abaixo são técnicos (tamanho, tempo, tentativas, teto de custo) e vêm da especificação já
 * aprovada — nenhum valor de negócio é decidido aqui.
 */

import { z } from "zod";

export const PROTOCOL_VERSION = "sal.agent-run/1.0";

export const LIMITS = {
  bodyBytes: 512 * 1024,
  systemPromptChars: 60_000,
  taskChars: 20_000,
  previousResultsItems: 20,
  previousResultItemChars: 100_000,
  previousResultsTotalChars: 300_000,
  businessDataBytes: 256 * 1024,
  timeoutSecondsMax: 240,
  attemptsMax: 3,
  maxCostPerCallUsd: 10,
  maxCostPerJobUsd: 100,
  idempotencyWindowDays: 7,
  authTimestampSkewSeconds: 300,
  /** Definição de agente enviada ao provider (Fase 5F). As atuais têm ~2 KB. */
  agentDefinitionChars: 20_000,
  /** Resultados de agentes numa revisão consolidada. */
  consolidationSources: 10,
} as const;

/** Autoridade do agente. Investigação não recomenda, não propõe, não aprova e não executa. */
export const agentAuthoritySchema = z
  .object({
    can_recommend: z.boolean(),
    can_propose: z.boolean(),
    can_approve: z.literal(false),
    can_execute: z.literal(false),
  })
  .strict();

export const evidenceSchema = z
  .object({
    id: z.string().trim().min(1).max(200),
    source: z.string().trim().min(1).max(500),
    period: z.string().trim().min(1).max(100),
    timestamp: z.string().datetime({ offset: true }),
    filters: z.record(z.unknown()).default({}),
    quality: z
      .object({
        source_quality: z.string().trim().min(1).max(50),
        completeness_pct: z.number().min(0).max(100).optional(),
        checks: z.array(z.string().max(300)).max(50).default([]),
      })
      .strict(),
    limitations: z.array(z.string().max(500)).max(50).default([]),
    data: z.unknown(),
  })
  .strict();

export const authorizedContextSchema = z
  .object({
    project: z.string().trim().min(1).max(200).regex(/^[a-zA-Z0-9_-]+$/),
    files: z.array(z.string().trim().min(1).max(300)).min(1).max(20),
  })
  .strict();

export const executionLimitsSchema = z
  .object({
    timeout_seconds: z.number().int().positive().max(LIMITS.timeoutSecondsMax),
    max_attempts: z.number().int().positive().max(LIMITS.attemptsMax),
    max_cost_usd_per_call: z.number().positive().max(LIMITS.maxCostPerCallUsd),
    max_cost_usd_per_job: z.number().positive().max(LIMITS.maxCostPerJobUsd),
  })
  .strict();

export const outputContractSchema = z
  .object({
    kind: z.literal("investigation"),
    schema_version: z.literal("sal.investigation-output/1.0"),
    require_json: z.literal(true),
  })
  .strict();

export const reviewPolicySchema = z
  .object({
    required: z.boolean(),
    max_correction_attempts: z.number().int().min(0).max(LIMITS.attemptsMax),
  })
  .strict();

/**
 * Contrato de saída da investigação. FATO ≠ CÁLCULO ≠ INFERÊNCIA ≠ HIPÓTESE, conforme
 * .claude/rules/diagnostic-quality.md do SAL OS. Autoridade de decisão não existe aqui.
 */
export const investigationOutputSchema = z
  .object({
    facts: z.array(z.string().max(2000)),
    calculations: z.array(z.string().max(2000)),
    inferences: z.array(z.string().max(2000)),
    hypotheses: z
      .array(
        z
          .object({
            statement: z.string().min(1).max(2000),
            favorable_evidence: z.array(z.string().max(1000)).default([]),
            contrary_evidence: z.array(z.string().max(1000)).default([]),
            missing_evidence: z.array(z.string().max(1000)).default([]),
            confidence: z.number().min(0).max(100),
          })
          .strict(),
      )
      .max(20),
    contradictions: z.array(z.string().max(2000)),
    missing_data: z.array(z.string().max(1000)),
    evidence: z.array(z.string().max(500)),
    confidence: z.number().min(0).max(100),
  })
  .strict();


/**
 * Revisão CONSOLIDADA (Fase 5F, MULTI_AGENT): o artefato é a consolidação determinística feita pelo SAL OS
 * dos resultados dos agentes. Não há autor de IA nesta execução — só o revisor independente, que não pode
 * ser nenhum dos providers que produziram os resultados consolidados.
 */
export const reviewTargetSchema = z
  .object({
    kind: z.literal("consolidated_investigation"),
    output: investigationOutputSchema,
    author_providers: z.array(z.enum(["anthropic", "openai"])).min(1).max(2),
    sources: z
      .array(
        z
          .object({
            agent: z.string().trim().min(1).max(100).regex(/^[a-z0-9-]+$/),
            status: z.string().trim().min(1).max(40),
            run_id: z.string().max(100).optional(),
            request_id: z.string().max(100).optional(),
          })
          .strict(),
      )
      .min(1)
      .max(LIMITS.consolidationSources),
  })
  .strict();

export const agentRunRequestSchema = z
  .object({
    protocol_version: z.literal(PROTOCOL_VERSION),
    request_id: z.string().uuid(),
    idempotency_key: z.string().trim().min(16).max(200),
    principal: z.string().trim().min(1).max(200),
    permission: z.literal("agent_run"),
    project: z.string().trim().min(1).max(200).regex(/^[a-zA-Z0-9_-]+$/),
    agent: z.string().trim().min(1).max(100).regex(/^[a-z0-9-]+$/),
    agent_version: z.string().trim().min(1).max(50),
    profile: z.enum(["fast", "balanced", "critical", "adversarial", "builder"]),
    task: z.string().trim().min(1).max(LIMITS.taskChars),
    authorized_context: authorizedContextSchema,
    evidence: z.array(evidenceSchema).max(50),
    previous_results: z
      .array(z.string().max(LIMITS.previousResultItemChars))
      .max(LIMITS.previousResultsItems)
      .default([]),
    business_data: z.record(z.unknown()).default({}),
    execution_limits: executionLimitsSchema,
    output_contract: outputContractSchema,
    review_policy: reviewPolicySchema,
    agent_authority: agentAuthoritySchema,
    review_target: reviewTargetSchema.optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.review_target && (!value.review_policy.required || value.review_policy.max_correction_attempts !== 0)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["review_policy"],
        message: "revisão consolidada exige review_policy.required=true e max_correction_attempts=0 (não há autor para corrigir).",
      });
    }
    const aggregated = value.previous_results.reduce((total, item) => total + item.length, 0);
    if (aggregated > LIMITS.previousResultsTotalChars) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["previous_results"],
        message: `previous_results agregado excede ${LIMITS.previousResultsTotalChars} caracteres.`,
      });
    }
    if (Buffer.byteLength(JSON.stringify(value.business_data), "utf8") > LIMITS.businessDataBytes) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["business_data"],
        message: `business_data excede ${LIMITS.businessDataBytes} bytes.`,
      });
    }
    if (value.authorized_context.project !== value.project) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["authorized_context", "project"],
        message: "authorized_context.project precisa ser o mesmo projeto do agent-run.",
      });
    }
  });

export type AgentRunRequest = z.infer<typeof agentRunRequestSchema>;
export type EvidenceItem = z.infer<typeof evidenceSchema>;

export type InvestigationOutput = z.infer<typeof investigationOutputSchema>;

/** Campos que pertencem ao SAL OS: um agent-run nunca pode devolvê-los. */
export const FORBIDDEN_OUTPUT_FIELDS = [
  "approved_decision",
  "approvedDecision",
  "execute_action",
  "executeAction",
  "executed_action",
  "verified_ok",
  "verifiedOk",
] as const;

export function forbiddenAuthorityFields(parsed: unknown): string[] {
  const found = new Set<string>();
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (node && typeof node === "object") {
      for (const [key, value] of Object.entries(node)) {
        if ((FORBIDDEN_OUTPUT_FIELDS as readonly string[]).includes(key)) found.add(key);
        walk(value);
      }
    }
  };
  walk(parsed);
  return [...found];
}

export type AgentRunStatus =
  | "succeeded"
  | "rejected_output"
  | "blocked_cost"
  | "blocked_security"
  | "failed_provider"
  | "timeout"
  | "needs_human";

export type CallOutcome =
  | "success"
  | "truncated"
  | "incomplete"
  | "timeout"
  | "rejected"
  | "provider_error"
  | "transport_error";

export interface AgentRunUsage {
  /** author = investigação; reviewer = revisão independente; correction = correção pedida pelo revisor. */
  role: "author" | "reviewer" | "correction";
  provider: string;
  /** Como a chamada terminou. Uma tentativa que falhou continua registrada — nunca some. */
  outcome: CallOutcome;
  /** reported = tokens informados pelo provider; unavailable_from_provider = o provider não informou. */
  usage_status: "reported" | "unavailable_from_provider";
  /** Requisições HTTP feitas nesta chamada (o agent-run desliga retentativas ocultas: esperado 1, ou 2 em adaptação de parâmetro). */
  provider_attempts: number | "unknown";
  failure_reason?: string;
  model: string | "unknown";
  input_tokens: number | "unknown";
  output_tokens: number | "unknown";
  total_tokens: number | "unknown";
  estimated_cost_usd: number | "unknown";
  reserved_cost_usd: number | "unknown";
  actual_cost_usd: number | "unknown";
  attempt: number;
  latency_ms: number;
}

export interface AgentRunResponse {
  protocol_version: typeof PROTOCOL_VERSION;
  request_id: string;
  run_id: string;
  status: AgentRunStatus;
  agent: string;
  agent_version: string;
  agent_authority: z.infer<typeof agentAuthoritySchema>;
  output?: InvestigationOutput;
  output_validation: { valid: boolean; reason: string };
  review: {
    required: boolean;
    reviewed: boolean;
    status: string;
    reviewer?: string;
    corrections: number;
    rejections?: string[];
    summary?: string;
    authority_violation?: boolean;
  };
  providers: {
    primary: string;
    primary_failure?: string;
    fallback_triggered: boolean;
    fallback_provider?: string;
    fallback_result?: string;
  };
  usage: AgentRunUsage[];
  context: {
    project: string;
    files_sent: string[];
    missing_context: string[];
    agent_definition: { path: string; status: string; sha256?: string };
  };
  /** investigation = autor + revisão; consolidated_review = só revisão de uma consolidação (MULTI_AGENT). */
  mode: "investigation" | "consolidated_review";
  evidence_received: string[];
  replayed: boolean;
  created_at: string;
}
