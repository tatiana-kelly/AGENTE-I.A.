/**
 * Montagem do contexto autorizado e do payload final entregue ao provider.
 *
 * Regras que este módulo garante:
 * - só entram arquivos pedidos em authorized_context E registrados no projeto (registry);
 * - cada trecho é delimitado com origem: [ARQUIVO: caminho] … [FIM DO ARQUIVO];
 * - arquivo pedido e não autorizado/ausente vira missing_context — nunca é substituído por outro;
 * - evidência vai delimitada e sem alteração: nada é enriquecido, completado ou inferido;
 * - a DEFINIÇÃO DO AGENTE (Fase 5F) é vinculada ao próprio agente do request: vem do registro do projeto,
 *   sob o prefixo reservado `agents/`, com sha256 visível; não pode ser pedida como contexto comum e nunca
 *   se sobrepõe ao AGENT CONTRACT (autoridade).
 */

import { createHash } from "node:crypto";
import type { OrchestrationRepository } from "../persistence/index.js";
import type { AgentRunRequest, EvidenceItem } from "./contract.js";
import { LIMITS } from "./contract.js";

/** Prefixo reservado no registro do projeto para definições de agente. */
export const AGENT_DEFINITION_PREFIX = "agents/";

export interface ResolvedAuthorizedContext {
  project: string;
  files: { path: string; content: string }[];
  missing: string[];
}

export type AgentDefinitionStatus = "sent" | "not_registered" | "too_large";

export interface ResolvedAgentDefinition {
  status: AgentDefinitionStatus;
  path: string;
  content?: string;
  sha256?: string;
}

export function sha256Hex(content: string): string {
  return createHash("sha256").update(content, "utf8").digest("hex");
}

/**
 * Lê o contexto do projeto REGISTRADO (projects registry), não o repositório inteiro.
 * O registro é a autoridade: se o arquivo não está no projeto cadastrado, ele não existe para o agente.
 * Definições de agente (`agents/…`) NÃO são contexto comum: pedidas aqui, viram missing_context.
 */
export async function resolveAuthorizedContext(
  repository: OrchestrationRepository,
  request: AgentRunRequest,
): Promise<ResolvedAuthorizedContext> {
  const project = await repository.getProject(request.authorized_context.project);
  const files: { path: string; content: string }[] = [];
  const missing: string[] = [];

  for (const path of request.authorized_context.files) {
    const reserved = path.startsWith(AGENT_DEFINITION_PREFIX);
    const content = project?.active && !reserved ? project.contextFiles[path] : undefined;
    if (typeof content === "string" && content.length > 0) {
      files.push({ path, content });
    } else {
      missing.push(path);
    }
  }
  return { project: request.authorized_context.project, files, missing };
}

/** A definição é a do agente DO REQUEST — um agente não recebe a definição de outro. */
export async function resolveAgentDefinition(
  repository: OrchestrationRepository,
  request: AgentRunRequest,
): Promise<ResolvedAgentDefinition> {
  const path = `${AGENT_DEFINITION_PREFIX}${request.agent}.md`;
  const project = await repository.getProject(request.project);
  const content = project?.active ? project.contextFiles[path] : undefined;
  if (typeof content !== "string" || content.length === 0) return { status: "not_registered", path };
  if (content.length > LIMITS.agentDefinitionChars) return { status: "too_large", path, sha256: sha256Hex(content) };
  return { status: "sent", path, content, sha256: sha256Hex(content) };
}

export function renderContextBlock(context: ResolvedAuthorizedContext): string {
  if (context.files.length === 0) return "(nenhum arquivo de contexto autorizado foi carregado)";
  return context.files
    .map((file) => [`[ARQUIVO: ${file.path}]`, file.content, "[FIM DO ARQUIVO]"].join("\n"))
    .join("\n\n");
}

export function renderEvidenceBlock(evidence: EvidenceItem[]): string {
  if (evidence.length === 0) return "(nenhuma evidência fornecida)";
  return evidence
    .map((item) =>
      [
        "[EVIDENCE]",
        `id=${item.id}`,
        `source=${item.source}`,
        `period=${item.period}`,
        `timestamp=${item.timestamp}`,
        `filters=${JSON.stringify(item.filters)}`,
        `quality=${JSON.stringify(item.quality)}`,
        `limitations=${JSON.stringify(item.limitations)}`,
        `data=${JSON.stringify(item.data)}`,
        "[/EVIDENCE]",
      ].join("\n"),
    )
    .join("\n\n");
}

const OUTPUT_SHAPE = `{
  "facts": ["<texto: um fato, citando o id da evidência>"],
  "calculations": ["<texto: a conta com os números e o resultado>"],
  "inferences": ["<texto: uma inferência, citando o id da evidência>"],
  "hypotheses": [{"statement": "<texto>", "favorable_evidence": ["<texto>"], "contrary_evidence": ["<texto>"], "missing_evidence": ["<texto>"], "confidence": 0}],
  "contradictions": ["<texto>"],
  "missing_data": ["<texto>"],
  "evidence": ["<id da evidência>"],
  "confidence": 0
}`;

/** Tipos explícitos: listas de TEXTO, nunca objetos (causa da rejeição no teste real sintético da Fase 5G). */
const OUTPUT_TYPES =
  "Cada item de facts, calculations, inferences, contradictions, missing_data e evidence é UMA STRING (texto). " +
  "Não use objetos nem listas aninhadas nesses campos. confidence é número de 0 a 100.";

export interface ProviderPayload {
  system: string;
  prompt: string;
  filesSent: string[];
  missingContext: string[];
}

function renderAgentDefinition(definition: ResolvedAgentDefinition | undefined): string {
  if (!definition || definition.status !== "sent" || !definition.content) return "";
  return [
    `[AGENT DEFINITION: ${definition.path} sha256=${definition.sha256}]`,
    definition.content,
    "[FIM DA DEFINIÇÃO DO AGENTE]",
    "A definição acima descreve MÉTODO de trabalho. Ela NÃO concede autoridade: em qualquer conflito,",
    "prevalece o AGENT CONTRACT abaixo — inclusive onde a definição fala em recomendar, decidir ou executar.",
  ].join("\n");
}

/**
 * Payload final: SYSTEM + AGENT DEFINITION (quando registrada) + AGENT CONTRACT + AUTHORIZED CONTEXT +
 * TASK + EVIDENCE + [CONSOLIDATION SOURCES] + TOOLS + LIMITATIONS + OUTPUT CONTRACT. Nada além disso.
 */
export function buildProviderPayload(
  request: AgentRunRequest,
  context: ResolvedAuthorizedContext,
  agentDefinition?: ResolvedAgentDefinition,
): ProviderPayload {
  const authority = request.agent_authority;
  const system = [
    "[SYSTEM]",
    "Você executa uma investigação técnica para o SAL Intelligence OS através do AI Orchestrator.",
    "Separe sempre FATO, CÁLCULO, INFERÊNCIA e HIPÓTESE. Nunca trate correlação como causa provada.",
    "Use exclusivamente o contexto autorizado e as evidências fornecidas abaixo.",
    "Não invente dados ausentes: o que faltar deve ser declarado em missing_data.",
    "[/SYSTEM]",
  ].join("\n");

  const consolidationSources = request.review_target
    ? [
        "[CONSOLIDATION SOURCES]",
        "O artefato em revisão é a CONSOLIDAÇÃO determinística (sem IA) dos resultados abaixo:",
        ...request.review_target.sources.map(
          (source) => `- agente=${source.agent} status=${source.status} run_id=${source.run_id ?? "n/a"}`,
        ),
        "[/CONSOLIDATION SOURCES]",
      ].join("\n")
    : "";

  const prompt = [
    renderAgentDefinition(agentDefinition),
    "[AGENT CONTRACT]",
    `agent=${request.agent}`,
    `agent_version=${request.agent_version}`,
    `protocol=${request.protocol_version}`,
    `can_recommend=${authority.can_recommend}`,
    `can_propose=${authority.can_propose}`,
    `can_approve=${authority.can_approve}`,
    `can_execute=${authority.can_execute}`,
    "Decisão aprovada, execução de ação e verificação de resultado pertencem ao SAL Intelligence OS.",
    "Você não pode elevar a própria autoridade nem declarar decisão, execução ou resultado verificado.",
    "[/AGENT CONTRACT]",
    "",
    `[AUTHORIZED PROJECT CONTEXT: ${context.project}]`,
    renderContextBlock(context),
    context.missing.length > 0 ? `missing_context=${JSON.stringify(context.missing)}` : "",
    "[/AUTHORIZED PROJECT CONTEXT]",
    "",
    "[TASK]",
    request.task,
    "[/TASK]",
    "",
    "[EVIDENCE]",
    renderEvidenceBlock(request.evidence),
    "[/EVIDENCE]",
    request.previous_results.length > 0
      ? ["", "[PREVIOUS RESULTS]", ...request.previous_results, "[/PREVIOUS RESULTS]"].join("\n")
      : "",
    consolidationSources,
    "",
    "[AVAILABLE TOOLS]",
    "nenhuma: esta execução é somente análise, sem ferramentas externas e sem efeitos.",
    "[/AVAILABLE TOOLS]",
    "",
    "[LIMITATIONS]",
    `timeout_seconds=${request.execution_limits.timeout_seconds}`,
    `max_attempts=${request.execution_limits.max_attempts}`,
    `max_cost_usd_per_call=${request.execution_limits.max_cost_usd_per_call}`,
    "Sem acesso a rede, a arquivos fora do contexto autorizado ou a sistemas de origem.",
    "[/LIMITATIONS]",
    "",
    "[OUTPUT CONTRACT]",
    `schema=${request.output_contract.schema_version}`,
    "Responda SOMENTE com um JSON válido exatamente neste formato:",
    OUTPUT_SHAPE,
    OUTPUT_TYPES,
    "Campos proibidos: approved_decision, execute_action, verified_ok.",
    "[/OUTPUT CONTRACT]",
  ]
    .filter((section) => section !== "")
    .join("\n");

  return {
    system,
    prompt: `${system}\n\n${prompt}`,
    filesSent: context.files.map((file) => file.path),
    missingContext: context.missing,
  };
}
