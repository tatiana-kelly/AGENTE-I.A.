/**
 * Camada HTTP do /v1/agent-runs: lê o corpo bruto (a assinatura cobre os bytes exatos), autentica com
 * SAL-HMAC-SHA256, valida o contrato e delega ao runner. Nenhuma dependência do Bearer do /orchestrate.
 *
 * Autenticação MÚTUA (Fase 5E): o cliente não confia num processo só porque ele está na porta certa.
 * - POST /v1/agent-runs/identity: o cliente manda só um desafio aleatório (nenhum dado de caso) e recebe
 *   uma prova HMAC que só quem tem o segredo compartilhado consegue produzir.
 * - Toda resposta a uma requisição autenticada sai assinada e amarrada ao nonce daquela requisição.
 */

import { z } from "zod";
import type { AgentRunAuthConfig, NonceStore } from "./auth.js";
import { authenticateAgentRun, sign } from "./auth.js";
import { LIMITS, PROTOCOL_VERSION, agentRunRequestSchema } from "./contract.js";
import type { AgentRunDependencies, AgentRunOutcome } from "./runner.js";
import { executeAgentRun } from "./runner.js";
import { bodyHashHex } from "./store.js";

export const AGENT_RUNS_PATH = "/v1/agent-runs";
export const AGENT_RUNS_IDENTITY_PATH = "/v1/agent-runs/identity";
export const PROTOCOL_HEADER = "X-SAL-Protocol";
export const RESPONSE_SIGNATURE_HEADER = "X-SAL-Response-Signature";

export interface AgentRunHttpDependencies extends AgentRunDependencies {
  auth: AgentRunAuthConfig;
  nonces: NonceStore;
}

export interface RawHttpRequest {
  method: string;
  path: string;
  contentType: string | undefined;
  authorization: string | undefined;
  /** Corpo bruto exatamente como recebido; undefined quando excedeu o limite. */
  body: string | undefined;
  tooLarge?: boolean;
}

export interface AgentRunHttpOutcome extends AgentRunOutcome {
  headers: Record<string, string>;
}

const identityRequestSchema = z.object({ challenge: z.string().min(16).max(200) }).strict();

/** Canônico da assinatura de resposta: amarra o corpo exato ao nonce da requisição que o originou. */
export function responseCanonical(nonce: string, serializedBody: string): string {
  return `${PROTOCOL_VERSION}\nresponse\n${nonce}\n${bodyHashHex(serializedBody)}`;
}

export function identityCanonical(challenge: string): string {
  return `${PROTOCOL_VERSION}\nidentity\n${challenge}`;
}

export async function handleAgentRunHttp(
  request: RawHttpRequest,
  dependencies: AgentRunHttpDependencies,
): Promise<AgentRunHttpOutcome> {
  const unsigned = (status: number, body: AgentRunOutcome["body"]): AgentRunHttpOutcome => ({
    status,
    body,
    headers: { [PROTOCOL_HEADER]: PROTOCOL_VERSION },
  });

  if (request.method.toUpperCase() !== "POST") {
    return unsigned(405, { error: "method_not_allowed", detail: "Use POST." });
  }
  if (request.tooLarge) {
    return unsigned(413, { error: "payload_too_large", detail: `Limite de ${LIMITS.bodyBytes} bytes.` });
  }
  if (!request.contentType?.toLowerCase().startsWith("application/json")) {
    return unsigned(415, { error: "unsupported_media_type", detail: "Content-Type deve ser application/json." });
  }
  const raw = request.body ?? "";

  const now = dependencies.clock?.() ?? new Date();
  const auth = await authenticateAgentRun(
    {
      method: request.method,
      path: request.path,
      authorizationHeader: request.authorization,
      bodyHash: bodyHashHex(raw),
      now,
    },
    dependencies.auth,
    dependencies.nonces,
  );
  if (!auth.ok) {
    // A assinatura recebida nunca é registrada nem devolvida. Sem autenticação, não há resposta assinada.
    return unsigned(auth.status, { error: auth.code, detail: auth.reason });
  }

  // Daqui em diante toda resposta é assinada: o cliente só confia no que o segredo compartilhado assinou.
  const signed = (outcome: AgentRunOutcome): AgentRunHttpOutcome => ({
    ...outcome,
    headers: {
      [PROTOCOL_HEADER]: PROTOCOL_VERSION,
      [RESPONSE_SIGNATURE_HEADER]: sign(dependencies.auth.secret, responseCanonical(auth.nonce, JSON.stringify(outcome.body))),
    },
  });

  let parsedBody: unknown;
  try {
    parsedBody = JSON.parse(raw);
  } catch {
    return signed({ status: 400, body: { error: "invalid_json", detail: "JSON inválido." } });
  }

  if (request.path === AGENT_RUNS_IDENTITY_PATH) {
    const identity = identityRequestSchema.safeParse(parsedBody);
    if (!identity.success) {
      return signed({ status: 400, body: { error: "invalid_request", detail: "Esperado {\"challenge\": string(16..200)}." } });
    }
    return signed({
      status: 200,
      body: {
        protocol_version: PROTOCOL_VERSION,
        service: "ai-orchestrator",
        challenge: identity.data.challenge,
        proof: sign(dependencies.auth.secret, identityCanonical(identity.data.challenge)),
      } as unknown as AgentRunOutcome["body"],
    });
  }

  const validated = agentRunRequestSchema.safeParse(parsedBody);
  if (!validated.success) {
    return signed({
      status: 400,
      body: {
        error: "invalid_request",
        detail: validated.error.issues
          .slice(0, 5)
          .map((issue: z.ZodIssue) => `${issue.path.join(".") || "(raiz)"}: ${issue.message}`)
          .join("; "),
      },
    });
  }

  if (validated.data.principal !== auth.principal) {
    return signed({
      status: 403,
      body: { error: "principal_mismatch", detail: "principal do corpo difere do principal assinado." },
    });
  }

  return signed(await executeAgentRun(validated.data, dependencies));
}
