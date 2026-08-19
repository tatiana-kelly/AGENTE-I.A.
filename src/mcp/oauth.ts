import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const ACCESS_TOKEN_TTL_SECONDS = 60 * 60;
const AUTHORIZATION_CODE_TTL_SECONDS = 5 * 60;
const REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60;

export interface McpOAuthConfig {
  issuer: string;
  clientId: string;
  clientSecret: string;
  connectorSecret: string;
  signingSecret: string;
  principalId: string;
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

export function validateAuthorizationRequest(url: URL, config: McpOAuthConfig) {
  const clientId = url.searchParams.get("client_id") ?? "";
  const redirectUri = url.searchParams.get("redirect_uri") ?? "";
  const responseType = url.searchParams.get("response_type") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const codeChallenge = url.searchParams.get("code_challenge") ?? "";
  const codeChallengeMethod = url.searchParams.get("code_challenge_method") ?? "";
  if (!safeEqual(clientId, config.clientId)) throw new OAuthError("invalid_client", "Cliente OAuth inválido.");
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
  const code = verifyToken(input.code, config.signingSecret, "authorization_code", config.clientId);
  if (!safeEqual(input.redirectUri, code.redirectUri ?? "")) throw new OAuthError("invalid_grant", "redirect_uri divergente.");
  const actualChallenge = pkceChallenge(input.codeVerifier);
  if (!safeEqual(actualChallenge, code.codeChallenge ?? "")) {
    throw new OAuthError("invalid_grant", "PKCE inválido.");
  }
  if (!(await consumeGrant(authorizationCodeGrantId(input.code)))) {
    throw new OAuthError("invalid_grant", "Código OAuth já utilizado ou expirado.");
  }
  return issueTokenPair(code.sub, config);
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
  const refresh = verifyToken(input.refreshToken, config.signingSecret, "refresh_token", config.clientId);
  return issueTokenPair(refresh.sub, config);
}

export function verifyAccessToken(token: string, config: McpOAuthConfig): { principalId: string } {
  const payload = verifyToken(token, config.signingSecret, "access_token", `${config.issuer}/mcp`);
  return { principalId: payload.sub };
}

function issueTokenPair(subject: string, config: McpOAuthConfig) {
  const accessToken = signToken({
    typ: "access_token",
    sub: subject,
    aud: `${config.issuer}/mcp`,
    ...timestamps(ACCESS_TOKEN_TTL_SECONDS),
  }, config.signingSecret);
  const refreshToken = signToken({
    typ: "refresh_token",
    sub: subject,
    aud: config.clientId,
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
  if (!safeEqual(clientId, config.clientId) || !safeEqual(clientSecret, config.clientSecret)) {
    throw new OAuthError("invalid_client", "Credenciais OAuth inválidas.", 401);
  }
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
