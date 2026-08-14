/**
 * Cliente HTTP compartilhado pelos 4 providers (FASE 2). Sem SDK — usa o
 * `fetch` global do Node — para manter a dependência mínima e o
 * comportamento fácil de testar com fetch mockado.
 */

export class ProviderHttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ProviderHttpError";
  }
}

export interface FetchJsonOptions extends RequestInit {
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export async function fetchJson<T>(url: string, options: FetchJsonOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const text = await response.text();
    const body = text.length > 0 ? safeJsonParse(text) : undefined;

    if (!response.ok) {
      const detail = typeof body === "string" ? body : JSON.stringify(body);
      throw new ProviderHttpError(response.status, body, `HTTP ${response.status} de ${url}: ${detail}`);
    }

    return body as T;
  } finally {
    clearTimeout(timeout);
  }
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
