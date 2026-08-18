import type { IncomingMessage, ServerResponse } from "node:http";
import { buildSupabaseRepositoryFromEnv } from "../persistence/index.js";
import { buildProviderManagerFromEnv } from "../providers/index.js";
import { createApiHandler } from "./app.js";

type ApiHandler = ReturnType<typeof createApiHandler>;

let handler: ApiHandler | undefined;

export default async function vercelHandler(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const originalUrl = request.url;
  request.url = normalizeVercelUrl(originalUrl);

  try {
    await getHandler()(request, response);
  } finally {
    request.url = originalUrl;
  }
}

export function normalizeVercelUrl(url: string | undefined): string {
  if (!url || url === "/api") return "/";
  const parsed = new URL(url, "http://orchestrator.local");
  const rewrittenRoute = parsed.searchParams.get("route");
  if (rewrittenRoute?.startsWith("/")) {
    parsed.searchParams.delete("route");
    const query = parsed.searchParams.toString();
    return `${rewrittenRoute}${query ? `?${query}` : ""}`;
  }
  return url.startsWith("/api/") ? url.slice("/api".length) : url;
}

function getHandler(): ApiHandler {
  if (handler) return handler;

  const repository = buildSupabaseRepositoryFromEnv();
  if (!repository) throw new Error("A API exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");

  const webhookSecret = process.env.N8N_WEBHOOK_SECRET?.trim();
  if (!webhookSecret) throw new Error("N8N_WEBHOOK_SECRET não configurado.");

  const { manager } = buildProviderManagerFromEnv();
  handler = createApiHandler({ repository, providerManager: manager, webhookSecret });
  return handler;
}
