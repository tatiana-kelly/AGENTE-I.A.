import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const ACCESS_TOKEN_TTL_SECONDS = 60 * 60;
const AUTHORIZATION_CODE_TTL_SECONDS = 5 * 60;
const REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60;
const DYNAMIC_CLIENT_PREFIX = "dyn_";

export interface McpOAuthConfig {
  issuer: string;
  clientId: string;
  clientSecret: string;
  connectorSecret: string;
  signingSecret: string;
  principalId: string;
  /** RFC 7591. Desligado por padrão — ligar amplia a superfície e é decisão explícita. */
  dynamicRegistration: boolean;
}

interface SignedTokenPayload {
  typ: "authorization_code" | "access_token" | "refresh_token";
  sub: string;
  aud: string;
  exp: number;
  iat: number;
  redirectUri?: string;
  codeChallenge?: string;
  nonce?: string;
}

export function loadMcpOAuthConfigFromEnv(origin: string): McpOAuthConfig {
  const configuredIssuer = process.env.MCP_OAUTH_ISSUER?.trim();
  if (process.env.NODE_ENV === "production" && !configuredIssuer) {
    throw new Error("MCP_OAUTH_ISSUER é obrigatório em produção.");
  }
  const config: McpOAuthConfig = {
    issuer: (configuredIssuer || origin).replace(/\/$/, ""),
    clientId: required("MCP_OAUTH_CLIENT_ID"),
    clientSecret: required("MCP_OAUTH_CLIENT_SECRET", 32),
    connectorSecret: required("MCP_CONNECTOR_SECRET", 32),
    signingSecret: required("MCP_TOKEN_SIGNING_SECRET", 32),
    principalId: required("MCP_PRINCIPAL_ID"),
    dynamicRegistration: process.env.MCP_OAUTH_DYNAMIC_REGISTRATION?.trim() === "true",
  };
  if (!config.issuer.startsWith("https://") && process.env.NODE_ENV === "production") {
    throw new Error("MCP_OAUTH_ISSUER deve usar HTTPS em produção.");
  }
  return config;
}

export function oauthMetadata(config: McpOAuthConfig) {
  return {
    issuer: config.issuer,
    authorization_endpoint: `${config.issuer}/oauth/authorize`,
    token_endpoint: `${config.issuer}/oauth/token`,
    // Só anunciado quando habilitado: um cliente que não vê o endpoint não
    // tenta registrar, e cai no caminho de client_id/secret pré-configurado.
    ...(config.dynamicRegistration ? { registration_endpoint: `${config.issuer}/oauth/register` } : {}),
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "refresh_token"],
    token_endpoint_auth_methods_supported: ["client_secret_post", "client_secret_basic"],
    code_challenge_methods_supported: ["S256"],
    scopes_supported: ["sal:projects:read", "sal:tasks:run", "sal:tasks:approve"],
  };
}

export function protectedResourceMetadata(config: McpOAuthConfig) {
  return {
    resource: `${config.issuer}/mcp`,
    authorization_servers: [config.issuer],
    bearer_methods_supported: ["header"],
    scopes_supported: ["sal:projects:read", "sal:tasks:run", "sal:tasks:approve"],
  };
}

/**
 * Registro dinâmico (RFC 7591) sem tabela nova: o `client_id` é
 * auto-verificável (semente aleatória + HMAC do issuer) e o `client_secret` é
 * derivado dele por HMAC. Assim o servidor reconhece um cliente que ele mesmo
 * emitiu sem guardar estado — o que também mantém o handler stateless na
 * Vercel, sem exigir migration antes de o conector funcionar.
 *
 * Trade-off registrado: não há revogação individual de cliente dinâmico. Para
 * invalidar todos de uma vez, troque `MCP_TOKEN_SIGNING_SECRET` (isso também
 * invalida tokens em circulação — é a saída de emergência, deliberada).
 *
 * O que impede abuso NÃO é o segredo do registro (RFC 7591 permite registro
 * aberto), e sim as duas barreiras que continuam de pé:
 *   1. `redirect_uris` limitados à mesma allowlist (claude.ai + loopback);
 *   2. a tela de autorização exige `MCP_CONNECTOR_SECRET` — sem ele, um
 *      cliente registrado não obtém nenhum código nem token.
 */
export function registerDynamicClient(body: unknown, config: McpOAuthConfig) {
  if (!config.dynamicRegistration) {
    throw new OAuthError("invalid_request", "Registro dinâmico de cliente está desabilitado.", 404);
  }
  const payload = (body ?? {}) as Record<string, unknown>;
  const redirectUris = payload.redirect_uris;
  if (!Array.isArray(redirectUris) || redirectUris.length === 0 || redirectUris.length > 5) {
    throw new OAuthError("invalid_redirect_uri", "redirect_uris é obrigatório (1 a 5 URIs).");
  }
  const uris = redirectUris.map((uri) => String(uri));
  // Mesma allowlist do fluxo de autorização: registrar não amplia destinos.
  const rejected = uris.find((uri) => !isAllowedRedirectUri(uri));
  if (rejected) {
    throw new OAuthError("invalid_redirect_uri", `redirect_uri não permitido: ${rejected}`);
  }
  const method = payload.token_endpoint_auth_method;
  if (method !== undefined && method !== "client_secret_post" && method !== "client_secret_basic") {
    throw new OAuthError("invalid_client_metadata", "token_endpoint_auth_method não suportado.");
  }

  const clientId = mintDynamicClientId(config.signingSecret);
  return {
    client_id: clientId,
    client_secret: deriveDynamicClientSecret(clientId, config.signingSecret),
    // 0 = sem expiração (RFC 7591 §3.2.1); a validade é a do signing secret.
    client_id_issued_at: nowSeconds(),
    client_secret_expires_at: 0,
    redirect_uris: uris,
    token_endpoint_auth_method: method ?? "client_secret_post",
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
    client_name: typeof payload.client_name === "string" ? payload.client_name.slice(0, 120) : "cliente-dinamico",
  };
}

export function validateAuthorizationRequest(url: URL, config: McpOAuthConfig) {
  const clientId = url.searchParams.get("client_id") ?? "";
  const redirectUri = url.searchParams.get("redirect_uri") ?? "";
  const responseType = url.searchParams.get("response_type") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const codeChallenge = url.searchParams.get("code_challenge") ?? "";
  const codeChallengeMethod = url.searchParams.get("code_challenge_method") ?? "";
  if (!isKnownClientId(clientId, config)) throw new OAuthError("invalid_client", "Cliente OAuth inválido.");
  if (responseType !== "code") throw new OAuthError("unsupported_response_type", "Somente authorization code é aceito.");
  if (!isAllowedRedirectUri(redirectUri)) throw new OAuthError("invalid_request", "redirect_uri não permitido.");
  if (!state) throw new OAuthError("invalid_request", "state obrigatório.");
  if (!codeChallenge || codeChallengeMethod !== "S256") throw new OAuthError("invalid_request", "PKCE S256 obrigatório.");
  return { clientId, redirectUri, state, codeChallenge };
}

export function issueAuthorizationCode(
  request: ReturnType<typeof validateAuthorizationRequest>,
  connectorSecret: string,
  config: McpOAuthConfig,
): string {
  if (!safeEqual(connectorSecret, config.connectorSecret)) {
    throw new OAuthError("access_denied", "Código de conexão inválido.");
  }
  return signToken({
    typ: "authorization_code",
    sub: config.principalId,
    aud: request.clientId,
    ...timestamps(AUTHORIZATION_CODE_TTL_SECONDS),
    redirectUri: request.redirectUri,
    codeChallenge: request.codeChallenge,
    nonce: randomBytes(16).toString("hex"),
  }, config.signingSecret);
}

export async function exchangeAuthorizationCode(input: {
  code: string;
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  codeVerifier: string;
}, config: McpOAuthConfig, consumeGrant: (grantId: string) => Promise<boolean>) {
  authenticateClient(input.clientId, input.clientSecret, config);
  const code = verifyToken(input.code, config.signingSecret, "authorization_code", input.clientId);
  if (!safeEqual(input.redirectUri, code.redirectUri ?? "")) throw new OAuthError("invalid_grant", "redirect_uri divergente.");
  const actualChallenge = pkceChallenge(input.codeVerifier);
  if (!safeEqual(actualChallenge, code.codeChallenge ?? "")) {
    throw new OAuthError("invalid_grant", "PKCE inválido.");
  }
  if (!(await consumeGrant(authorizationCodeGrantId(input.code)))) {
    throw new OAuthError("invalid_grant", "Código OAuth já utilizado ou expirado.");
  }
  return issueTokenPair(code.sub, config, input.clientId);
}

export function authorizationCodeGrantId(code: string): string {
  return createHash("sha256").update(code).digest("hex");
}

export function authorizationCodeExpiresAt(): string {
  return new Date(Date.now() + AUTHORIZATION_CODE_TTL_SECONDS * 1000).toISOString();
}

export function refreshAccessToken(input: {
  refreshToken: string;
  clientId: string;
  clientSecret: string;
}, config: McpOAuthConfig) {
  authenticateClient(input.clientId, input.clientSecret, config);
  const refresh = verifyToken(input.refreshToken, config.signingSecret, "refresh_token", input.clientId);
  return issueTokenPair(refresh.sub, config, input.clientId);
}

export function verifyAccessToken(token: string, config: McpOAuthConfig): { principalId: string } {
  const payload = verifyToken(token, config.signingSecret, "access_token", `${config.issuer}/mcp`);
  return { principalId: payload.sub };
}

function issueTokenPair(subject: string, config: McpOAuthConfig, clientId: string) {
  const accessToken = signToken({
    typ: "access_token",
    sub: subject,
    aud: `${config.issuer}/mcp`,
    ...timestamps(ACCESS_TOKEN_TTL_SECONDS),
  }, config.signingSecret);
  const refreshToken = signToken({
    typ: "refresh_token",
    sub: subject,
    aud: clientId,
    ...timestamps(REFRESH_TOKEN_TTL_SECONDS),
    nonce: randomBytes(16).toString("hex"),
  }, config.signingSecret);
  return {
    access_token: accessToken,
    token_type: "Bearer",
    expires_in: ACCESS_TOKEN_TTL_SECONDS,
    refresh_token: refreshToken,
    scope: "sal:projects:read sal:tasks:run sal:tasks:approve",
  };
}

function authenticateClient(clientId: string, clientSecret: string, config: McpOAuthConfig): void {
  if (safeEqual(clientId, config.clientId) && safeEqual(clientSecret, config.clientSecret)) return;
  if (
    isDynamicClientId(clientId, config)
    && safeEqual(clientSecret, deriveDynamicClientSecret(clientId, config.signingSecret))
  ) return;
  throw new OAuthError("invalid_client", "Credenciais OAuth inválidas.", 401);
}

/** Aceita o cliente estático pré-configurado ou um dinâmico emitido por este servidor. */
function isKnownClientId(clientId: string, config: McpOAuthConfig): boolean {
  return safeEqual(clientId, config.clientId) || isDynamicClientId(clientId, config);
}

/**
 * Verifica que o `client_id` foi emitido por este servidor, recalculando o MAC
 * da semente. Sem isso, qualquer string com prefixo `dyn_` passaria.
 */
function isDynamicClientId(clientId: string, config: McpOAuthConfig): boolean {
  if (!config.dynamicRegistration || !clientId.startsWith(DYNAMIC_CLIENT_PREFIX)) return false;
  const seed = clientId.slice(DYNAMIC_CLIENT_PREFIX.length).split(".")[0] ?? "";
  if (!seed) return false;
  return safeEqual(clientId, signDynamicClientId(seed, config.signingSecret));
}

function mintDynamicClientId(signingSecret: string): string {
  return signDynamicClientId(randomBytes(16).toString("base64url"), signingSecret);
}

function signDynamicClientId(seed: string, signingSecret: string): string {
  const mac = createHmac("sha256", signingSecret).update(`dcr-client:${seed}`).digest("base64url").slice(0, 27);
  return `${DYNAMIC_CLIENT_PREFIX}${seed}.${mac}`;
}

function deriveDynamicClientSecret(clientId: string, signingSecret: string): string {
  return createHmac("sha256", signingSecret).update(`dcr-secret:${clientId}`).digest("base64url");
}

function signToken(payload: SignedTokenPayload, secret: string): string {
  const encoded = base64Url(Buffer.from(JSON.stringify(payload), "utf8"));
  const signature = base64Url(createHmac("sha256", secret).update(encoded).digest());
  return `${encoded}.${signature}`;
}

function verifyToken(token: string, secret: string, type: SignedTokenPayload["typ"], audience: string): SignedTokenPayload {
  const [encoded, signature, extra] = token.split(".");
  if (!encoded || !signature || extra) throw new OAuthError("invalid_grant", "Token inválido.");
  const expected = base64Url(createHmac("sha256", secret).update(encoded).digest());
  if (!safeEqual(signature, expected)) throw new OAuthError("invalid_grant", "Token inválido.");
  let payload: SignedTokenPayload;
  try {
    payload = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as SignedTokenPayload;
  } catch {
    throw new OAuthError("invalid_grant", "Token inválido.");
  }
  if (payload.typ !== type || !safeEqual(payload.aud, audience) || payload.exp <= nowSeconds()) {
    throw new OAuthError("invalid_grant", "Token expirado ou inválido.");
  }
  return payload;
}

function timestamps(ttlSeconds: number) {
  const iat = nowSeconds();
  return { iat, exp: iat + ttlSeconds };
}

function isAllowedRedirectUri(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.href === "https://claude.ai/api/mcp/auth_callback") return true;
    return url.protocol === "http:"
      && (url.hostname === "localhost" || url.hostname === "127.0.0.1")
      && url.pathname === "/callback"
      && !url.username
      && !url.password;
  } catch {
    return false;
  }
}

function required(name: string, minLength = 3): string {
  const value = process.env[name]?.trim();
  if (!value || value.length < minLength) throw new Error(`${name} deve ter ao menos ${minLength} caracteres.`);
  return value;
}

function safeEqual(received: string, expected: string): boolean {
  const left = Buffer.from(received, "utf8");
  const right = Buffer.from(expected, "utf8");
  return left.length === right.length && timingSafeEqual(left, right);
}

function base64Url(value: Buffer): string {
  return value.toString("base64url");
}

function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export class OAuthError extends Error {
  constructor(readonly code: string, message: string, readonly statusCode = 400) {
    super(message);
  }
}
