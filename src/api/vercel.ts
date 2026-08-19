import type { IncomingMessage, ServerResponse } from "node:http";
import { buildSupabaseRepositoryFromEnv } from "../persistence/index.js";
import { buildProviderManagerFromEnv } from "../providers/index.js";
import { createApiHandler } from "./app.js";
import { createMcpHttpHandler } from "../mcp/http.js";

type ApiHandler = ReturnType<typeof createApiHandler>;
type McpHandler = ReturnType<typeof createMcpHttpHandler>;

let handler: ApiHandler | undefined;
let mcpHandler: McpHandler | undefined;

export default async function vercelHandler(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const originalUrl = request.url;
  request.url = normalizeVercelUrl(originalUrl);

  try {
    if (isMcpRoute(request.url)) {
      await getMcpHandler()(request, response);
      return;
    }
    await getHandler()(request, response);
  } finally {
    request.url = originalUrl;
  }
}

function isMcpRoute(url: string | undefined): boolean {
  const pathname = new URL(url ?? "/", "http://orchestrator.local").pathname;
  return pathname === "/mcp" || pathname.startsWith("/oauth/") || pathname.startsWith("/.well-known/");
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

function getMcpHandler(): McpHandler {
  if (mcpHandler) return mcpHandler;
  const repository = buildSupabaseRepositoryFromEnv();
  if (!repository) throw new Error("O MCP exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");
  const { manager } = buildProviderManagerFromEnv();
  mcpHandler = createMcpHttpHandler({ repository, providerManager: manager });
  return mcpHandler;
}
