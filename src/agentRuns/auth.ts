/**
 * SAL-HMAC-SHA256 — autenticação própria do /v1/agent-runs.
 *
 * Não usa N8N_WEBHOOK_SECRET nem o Bearer do /orchestrate: o segredo vem de AGENT_RUN_HMAC_SECRET e
 * nunca aparece em log, resposta ou erro. A assinatura cobre método, rota, timestamp, nonce, principal
 * e o corpo inteiro, então nenhum campo pode ser trocado em trânsito.
 *
 * Header:
 *   Authorization: SAL-HMAC-SHA256 principal=...,timestamp=...,nonce=...,signature=<hex>
 * String canônica:
 *   METHOD\nPATH\ntimestamp\nnonce\nprincipal\nsha256(body em hex)
 */

import { createHmac, timingSafeEqual } from "node:crypto";
import { LIMITS } from "./contract.js";

export const AUTH_SCHEME = "SAL-HMAC-SHA256";
export const AGENT_RUN_PERMISSION = "agent_run";

export interface AgentRunAuthConfig {
  secret: string;
  /** Principais autorizados a executar agent-run — nunca um curinga. */
  allowedPrincipals: readonly string[];
  skewSeconds?: number;
}

export interface AuthAttempt {
  method: string;
  path: string;
  authorizationHeader: string | undefined;
  bodyHash: string;
  now: Date;
}

export type AuthFailureCode = "missing" | "malformed" | "stale" | "replay" | "signature" | "principal";

export interface AuthSuccess {
  ok: true;
  principal: string;
  nonce: string;
}

export interface AuthFailure {
  ok: false;
  code: AuthFailureCode;
  status: 401 | 403;
  reason: string;
}

export type AuthResult = AuthSuccess | AuthFailure;

/** Registro de nonces já usados — impede replay dentro da janela de tolerância. */
export interface NonceStore {
  /** `now` vem do relógio da requisição: a limpeza nunca depende do relógio do processo. */
  consume(nonce: string, expiresAt: Date, now: Date): Promise<boolean>;
}

export class InMemoryNonceStore implements NonceStore {
  private readonly seen = new Map<string, number>();

  async consume(nonce: string, expiresAt: Date, now: Date): Promise<boolean> {
    const reference = now.getTime();
    for (const [key, expiry] of this.seen) if (expiry <= reference) this.seen.delete(key);
    if (this.seen.has(nonce)) return false;
    this.seen.set(nonce, expiresAt.getTime());
    return true;
  }
}

function parseHeader(header: string): Record<string, string> | undefined {
  if (!header.startsWith(`${AUTH_SCHEME} `)) return undefined;
  const parts = header.slice(AUTH_SCHEME.length + 1).split(",");
  const parsed: Record<string, string> = {};
  for (const part of parts) {
    const index = part.indexOf("=");
    if (index <= 0) return undefined;
    parsed[part.slice(0, index).trim()] = part.slice(index + 1).trim();
  }
  return parsed;
}

export function canonicalString(params: {
  method: string;
  path: string;
  timestamp: string;
  nonce: string;
  principal: string;
  bodyHash: string;
}): string {
  return [params.method.toUpperCase(), params.path, params.timestamp, params.nonce, params.principal, params.bodyHash].join("\n");
}

export function sign(secret: string, canonical: string): string {
  return createHmac("sha256", secret).update(canonical, "utf8").digest("hex");
}

function safeEquals(a: string, b: string): boolean {
  const left = Buffer.from(a, "utf8");
  const right = Buffer.from(b, "utf8");
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function authenticateAgentRun(
  attempt: AuthAttempt,
  config: AgentRunAuthConfig,
  nonces: NonceStore,
): Promise<AuthResult> {
  if (!attempt.authorizationHeader) {
    return { ok: false, code: "missing", status: 401, reason: "Assinatura ausente." };
  }
  const parsed = parseHeader(attempt.authorizationHeader);
  if (!parsed?.principal || !parsed.timestamp || !parsed.nonce || !parsed.signature) {
    return { ok: false, code: "malformed", status: 401, reason: "Cabeçalho de assinatura malformado." };
  }
  if (parsed.nonce.length < 8 || parsed.nonce.length > 200) {
    return { ok: false, code: "malformed", status: 401, reason: "Nonce inválido." };
  }

  const timestamp = new Date(parsed.timestamp);
  if (Number.isNaN(timestamp.getTime())) {
    return { ok: false, code: "malformed", status: 401, reason: "Timestamp inválido." };
  }
  const skewSeconds = config.skewSeconds ?? LIMITS.authTimestampSkewSeconds;
  if (Math.abs(attempt.now.getTime() - timestamp.getTime()) > skewSeconds * 1000) {
    return { ok: false, code: "stale", status: 401, reason: "Timestamp fora da janela permitida." };
  }

  const expected = sign(
    config.secret,
    canonicalString({
      method: attempt.method,
      path: attempt.path,
      timestamp: parsed.timestamp,
      nonce: parsed.nonce,
      principal: parsed.principal,
      bodyHash: attempt.bodyHash,
    }),
  );
  if (!safeEquals(parsed.signature, expected)) {
    return { ok: false, code: "signature", status: 401, reason: "Assinatura inválida." };
  }

  // Principal só é avaliado depois da assinatura: assim um principal inválido não vira oráculo de nomes.
  if (!config.allowedPrincipals.includes(parsed.principal)) {
    return { ok: false, code: "principal", status: 403, reason: "Principal não autorizado para agent_run." };
  }

  const fresh = await nonces.consume(parsed.nonce, new Date(timestamp.getTime() + skewSeconds * 1000), attempt.now);
  if (!fresh) {
    return { ok: false, code: "replay", status: 401, reason: "Nonce já utilizado (replay)." };
  }

  return { ok: true, principal: parsed.principal, nonce: parsed.nonce };
}

export function loadAgentRunAuthFromEnv(env: NodeJS.ProcessEnv = process.env): AgentRunAuthConfig | undefined {
  const secret = env.AGENT_RUN_HMAC_SECRET?.trim();
  if (!secret || secret.length < 32) return undefined; // fail-closed: sem segredo forte, a rota não autentica
  const principals = (env.AGENT_RUN_PRINCIPALS ?? "service:sal-intelligence-os")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return { secret, allowedPrincipals: principals };
}
