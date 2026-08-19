import type { IncomingHttpHeaders, IncomingMessage, ServerResponse } from "node:http";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import type { ProviderManager } from "../orchestrator/providerManager.js";
import { orchestrate } from "../orchestrator/index.js";
import { loadExecutionModeFromEnv } from "../orchestrator/securityLayer.js";
import type { OrchestrationRepository } from "../persistence/index.js";
import { createProjectMcpServer } from "./server.js";
import {
  OAuthError,
  authorizationCodeExpiresAt,
  authorizationCodeGrantId,
  exchangeAuthorizationCode,
  issueAuthorizationCode,
  loadMcpOAuthConfigFromEnv,
  oauthMetadata,
  protectedResourceMetadata,
  refreshAccessToken,
  validateAuthorizationRequest,
  verifyAccessToken,
} from "./oauth.js";

const MAX_AUTH_BODY_BYTES = 16 * 1024;

export interface McpHttpDependencies {
  repository: OrchestrationRepository;
  providerManager: ProviderManager;
}

export function createMcpHttpHandler(dependencies: McpHttpDependencies) {
  return async (request: IncomingMessage, response: ServerResponse): Promise<void> => {
    const origin = publicOrigin(request.headers);
    const config = loadMcpOAuthConfigFromEnv(origin);
    const url = new URL(request.url ?? "/", origin);

    try {
      if (request.method === "GET" && (url.pathname === "/.well-known/oauth-authorization-server" || url.pathname === "/.well-known/openid-configuration")) {
        return writeJson(response, 200, oauthMetadata(config));
      }
      if (request.method === "GET" && (url.pathname === "/.well-known/oauth-protected-resource" || url.pathname === "/.well-known/oauth-protected-resource/mcp")) {
        return writeJson(response, 200, protectedResourceMetadata(config));
      }
      if (request.method === "GET" && url.pathname === "/oauth/authorize") {
        const authorization = validateAuthorizationRequest(url, config);
        return writeHtml(response, authorizationPage(url.searchParams, authorization.redirectUri));
      }
      if (request.method === "POST" && url.pathname === "/oauth/authorize") {
        const form = await readForm(request);
        const authorizationUrl = new URL(`/oauth/authorize?${form.get("authorization_query") ?? ""}`, origin);
        const authorization = validateAuthorizationRequest(authorizationUrl, config);
        const code = issueAuthorizationCode(authorization, form.get("connector_secret") ?? "", config);
        await dependencies.repository.createOAuthGrant(authorizationCodeGrantId(code), authorizationCodeExpiresAt());
        const redirect = new URL(authorization.redirectUri);
        redirect.searchParams.set("code", code);
        redirect.searchParams.set("state", authorization.state);
        response.writeHead(302, { Location: redirect.href, "Cache-Control": "no-store" });
        response.end();
        return;
      }
      if (request.method === "POST" && url.pathname === "/oauth/token") {
        const form = await readForm(request);
        const client = clientCredentials(request.headers.authorization, form);
        const grantType = form.get("grant_type");
        const tokens = grantType === "authorization_code"
          ? await exchangeAuthorizationCode({
              code: form.get("code") ?? "",
              clientId: client.clientId,
              clientSecret: client.clientSecret,
              redirectUri: form.get("redirect_uri") ?? "",
              codeVerifier: form.get("code_verifier") ?? "",
            }, config, (grantId) => dependencies.repository.consumeOAuthGrant(grantId, new Date().toISOString()))
          : grantType === "refresh_token"
            ? refreshAccessToken({
                refreshToken: form.get("refresh_token") ?? "",
                clientId: client.clientId,
                clientSecret: client.clientSecret,
              }, config)
            : (() => { throw new OAuthError("unsupported_grant_type", "grant_type não suportado."); })();
        return writeJson(response, 200, tokens);
      }
      if (url.pathname === "/mcp" && request.method === "OPTIONS") {
        response.writeHead(204, corsHeaders());
        response.end();
        return;
      }
      if (url.pathname === "/mcp") {
        const token = bearerToken(request.headers.authorization);
        if (!token) return unauthorized(response, origin);
        let principalId: string;
        try {
          principalId = verifyAccessToken(token, config).principalId;
        } catch {
          return unauthorized(response, origin);
        }
        const transport = new WebStandardStreamableHTTPServerTransport({
          sessionIdGenerator: undefined,
          enableJsonResponse: true,
        });
        const server = createProjectMcpServer({
          repository: dependencies.repository,
          principal: { type: "agent", id: principalId },
          runTask: (input) => orchestrate(input, {
            repository: dependencies.repository,
            providerManager: dependencies.providerManager,
            security: loadExecutionModeFromEnv(),
          }),
        });
        await server.connect(transport);
        const webRequest = await toWebRequest(request, url);
        const webResponse = await transport.handleRequest(webRequest);
        return pipeWebResponse(response, webResponse);
      }
      writeJson(response, 404, { error: "Endpoint MCP/OAuth não encontrado." });
    } catch (error) {
      if (error instanceof OAuthError) {
        return writeJson(response, error.statusCode, { error: error.code, error_description: error.message });
      }
      writeJson(response, 500, { error: "server_error", error_description: "Falha interna do conector." });
    }
  };
}

function authorizationPage(params: URLSearchParams, redirectUri: string): string {
  const query = escapeHtml(params.toString());
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Autorizar SAL AI Orchestrator</title></head><body><main><h1>SAL AI Orchestrator</h1><p>Autorize o Claude a acessar somente os projetos concedidos a este agente.</p><p>Retorno: <code>${escapeHtml(new URL(redirectUri).origin)}</code></p><form method="post" action="/oauth/authorize"><input type="hidden" name="authorization_query" value="${query}"><label>Código privado de conexão <input type="password" name="connector_secret" minlength="32" required autocomplete="one-time-code"></label><button type="submit">Autorizar</button></form><p>Nunca informe a chave service_role nesta página.</p></main></body></html>`;
}

function clientCredentials(authorization: string | undefined, form: URLSearchParams) {
  if (authorization?.startsWith("Basic ")) {
    const decoded = Buffer.from(authorization.slice(6), "base64").toString("utf8");
    const separator = decoded.indexOf(":");
    if (separator >= 0) return { clientId: decoded.slice(0, separator), clientSecret: decoded.slice(separator + 1) };
  }
  return { clientId: form.get("client_id") ?? "", clientSecret: form.get("client_secret") ?? "" };
}

function bearerToken(authorization: string | undefined): string | undefined {
  return authorization?.startsWith("Bearer ") ? authorization.slice(7).trim() : undefined;
}

function unauthorized(response: ServerResponse, origin: string): void {
  writeJson(response, 401, { error: "invalid_token" }, {
    "WWW-Authenticate": `Bearer resource_metadata="${origin}/.well-known/oauth-protected-resource/mcp"`,
  });
}

function publicOrigin(headers: IncomingHttpHeaders): string {
  const proto = first(headers["x-forwarded-proto"]) || "https";
  const host = first(headers["x-forwarded-host"]) || first(headers.host);
  if (!host) throw new Error("Host público ausente.");
  return `${proto}://${host}`;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

async function readForm(request: IncomingMessage): Promise<URLSearchParams> {
  const type = request.headers["content-type"]?.toLowerCase() ?? "";
  if (!type.startsWith("application/x-www-form-urlencoded")) throw new OAuthError("invalid_request", "Formulário inválido.");
  const body = await readBody(request, MAX_AUTH_BODY_BYTES);
  return new URLSearchParams(body.toString("utf8"));
}

async function toWebRequest(request: IncomingMessage, url: URL): Promise<Request> {
  const body = request.method === "GET" || request.method === "HEAD" ? undefined : await readBody(request, 256 * 1024);
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    if (value !== undefined) headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  return new Request(url, { method: request.method, headers, body });
}

async function readBody(request: IncomingMessage, limit: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > limit) throw new OAuthError("invalid_request", "Payload excede o limite.", 413);
    chunks.push(buffer);
  }
  return Buffer.concat(chunks);
}

async function pipeWebResponse(response: ServerResponse, webResponse: Response): Promise<void> {
  const headers: Record<string, string> = { ...corsHeaders() };
  webResponse.headers.forEach((value, key) => { headers[key] = value; });
  response.writeHead(webResponse.status, headers);
  if (webResponse.body) {
    for await (const chunk of webResponse.body) response.write(Buffer.from(chunk));
  }
  response.end();
}

function writeJson(response: ServerResponse, status: number, body: unknown, extra: Record<string, string> = {}): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload).toString(),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    ...extra,
  });
  response.end(payload);
}

function writeHtml(response: ServerResponse, body: string): void {
  response.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

function corsHeaders(): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Authorization,Content-Type,Mcp-Protocol-Version,Mcp-Session-Id,Last-Event-ID",
    "Access-Control-Expose-Headers": "Mcp-Protocol-Version,Mcp-Session-Id,WWW-Authenticate",
  };
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character] ?? character);
}
