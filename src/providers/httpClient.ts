/**
 * Cliente HTTP compartilhado pelos 4 providers (FASE 2). Sem SDK — usa o
 * `fetch` global do Node — para manter a dependência mínima e o
 * comportamento fácil de testar com fetch mockado.
 */

export class ProviderHttpError extends Error {
  /** Preenchido a partir do header `Retry-After`, quando o servidor o envia. */
  retryAfterMs?: number;

  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ProviderHttpError";
  }
}

/**
 * Política de retry. `"safe"` (default) cobre requisições sem efeito
 * colateral: repete em 429 e 5xx. `"rate-limit-only"` é para requisições
 * NÃO idempotentes (ex.: `task.create` do Manus, que dispara execução real):
 * só 429 é repetido, porque rate-limit significa que o servidor recusou
 * antes de processar; um 5xx pode ter criado a task do outro lado e repetir
 * criaria uma segunda execução. `"none"` desliga.
 */
export type RetryPolicy = "safe" | "rate-limit-only" | "none";

export interface FetchJsonOptions extends RequestInit {
  timeoutMs?: number;
  retryPolicy?: RetryPolicy;
  /** Total de tentativas, incluindo a primeira. Default 3. */
  maxAttempts?: number;
  /** Injetável para teste — evita esperar de verdade. */
  sleepFn?: (ms: number) => Promise<void>;
}

const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_ATTEMPTS = 3;
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 8_000;

export async function fetchJson<T>(url: string, options: FetchJsonOptions = {}): Promise<T> {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retryPolicy = "safe",
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    sleepFn = defaultSleep,
    ...init
  } = options;

  const attempts = retryPolicy === "none" ? 1 : Math.max(1, maxAttempts);
  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchJsonOnce<T>(url, init, timeoutMs);
    } catch (error) {
      lastError = error;
      const isLastAttempt = attempt === attempts;
      if (isLastAttempt || !shouldRetry(error, retryPolicy)) {
        throw error;
      }
      await sleepFn(backoffDelayMs(attempt, error));
    }
  }

  throw lastError;
}

async function fetchJsonOnce<T>(url: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const text = await response.text();
    const body = text.length > 0 ? safeJsonParse(text) : undefined;

    if (!response.ok) {
      const detail = typeof body === "string" ? body : JSON.stringify(body);
      const error = new ProviderHttpError(response.status, body, `HTTP ${response.status} de ${url}: ${detail}`);
      error.retryAfterMs = parseRetryAfter(response.headers.get("retry-after"));
      throw error;
    }

    return body as T;
  } finally {
    clearTimeout(timeout);
  }
}

function shouldRetry(error: unknown, policy: RetryPolicy): boolean {
  if (policy === "none") return false;
  if (error instanceof ProviderHttpError) {
    if (error.status === 429) return true;
    // 5xx só é repetido quando a requisição é comprovadamente sem efeito colateral.
    return policy === "safe" && error.status >= 500;
  }
  // Erro de rede (fetch rejeitou sem resposta) — só repetido na política "safe".
  // AbortError é timeout nosso: repetir tende a estourar de novo, então não repete.
  if (error instanceof Error && error.name !== "AbortError") {
    return policy === "safe";
  }
  return false;
}

/** Backoff exponencial com jitter; respeita `Retry-After` do servidor quando presente. */
function backoffDelayMs(attempt: number, error: unknown): number {
  if (error instanceof ProviderHttpError && error.retryAfterMs !== undefined) {
    return Math.min(error.retryAfterMs, MAX_BACKOFF_MS);
  }
  const exponential = Math.min(BASE_BACKOFF_MS * 2 ** (attempt - 1), MAX_BACKOFF_MS);
  return exponential + Math.floor(Math.random() * 250);
}

function parseRetryAfter(header: string | null): number | undefined {
  if (!header) return undefined;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : undefined;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function describeProviderError(error: unknown): string {
  if (error instanceof ProviderHttpError) {
    return `HTTP ${error.status}`;
  }
  if (error instanceof Error) {
    return error.name === "AbortError" ? "timeout" : error.message;
  }
  return String(error);
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
