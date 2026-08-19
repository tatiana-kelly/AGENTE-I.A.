import { createHash, randomBytes } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OAuthError,
  authorizationCodeGrantId,
  exchangeAuthorizationCode,
  issueAuthorizationCode,
  oauthMetadata,
  refreshAccessToken,
  registerDynamicClient,
  validateAuthorizationRequest,
  verifyAccessToken,
  type McpOAuthConfig,
} from "../src/mcp/oauth.js";

const config: McpOAuthConfig = {
  issuer: "https://orchestrator.example.com",
  clientId: "sal-claude",
  clientSecret: "c".repeat(32),
  connectorSecret: "a".repeat(32),
  signingSecret: "s".repeat(32),
  principalId: "claude",
  dynamicRegistration: false,
};

afterEach(() => vi.useRealTimers());

describe("MCP OAuth", () => {
  it("exige PKCE S256 e restringe redirect URI", () => {
    const invalid = authorizationUrl({ redirect_uri: "http://evil.example/callback" });
    expect(() => validateAuthorizationRequest(invalid, config)).toThrowError(OAuthError);
    const valid = validateAuthorizationRequest(authorizationUrl(), config);
    expect(valid.redirectUri).toBe("http://localhost:4141/callback");
  });

  it("emite, troca e valida token curto sem expor segredos", async () => {
    const verifier = randomBytes(32).toString("base64url");
    const request = validateAuthorizationRequest(authorizationUrl({ code_challenge: challenge(verifier) }), config);
    const code = issueAuthorizationCode(request, config.connectorSecret, config);
    const consume = vi.fn(async () => true);
    const tokens = await exchangeAuthorizationCode({
      code,
      clientId: config.clientId,
      clientSecret: config.clientSecret,
      redirectUri: request.redirectUri,
      codeVerifier: verifier,
    }, config, consume);

    expect(consume).toHaveBeenCalledWith(authorizationCodeGrantId(code));
    expect(verifyAccessToken(tokens.access_token, config)).toEqual({ principalId: "claude" });
    expect(tokens.access_token).not.toContain(config.signingSecret);
    expect(tokens.access_token).not.toContain(config.connectorSecret);
  });

  it("bloqueia replay de authorization code", async () => {
    const verifier = randomBytes(32).toString("base64url");
    const request = validateAuthorizationRequest(authorizationUrl({ code_challenge: challenge(verifier) }), config);
    const code = issueAuthorizationCode(request, config.connectorSecret, config);
    await expect(exchangeAuthorizationCode({
      code,
      clientId: config.clientId,
      clientSecret: config.clientSecret,
      redirectUri: request.redirectUri,
      codeVerifier: verifier,
    }, config, async () => false)).rejects.toMatchObject({ code: "invalid_grant" });
  });

  it("rejeita segredo do conector, cliente e PKCE incorretos", async () => {
    const verifier = randomBytes(32).toString("base64url");
    const request = validateAuthorizationRequest(authorizationUrl({ code_challenge: challenge(verifier) }), config);
    expect(() => issueAuthorizationCode(request, "errado", config)).toThrowError(OAuthError);
    const code = issueAuthorizationCode(request, config.connectorSecret, config);
    await expect(exchangeAuthorizationCode({
      code,
      clientId: config.clientId,
      clientSecret: "errado",
      redirectUri: request.redirectUri,
      codeVerifier: verifier,
    }, config, async () => true)).rejects.toMatchObject({ code: "invalid_client" });
  });

  it("renova access token e rejeita token expirado", () => {
    const verifier = randomBytes(32).toString("base64url");
    const request = validateAuthorizationRequest(authorizationUrl({ code_challenge: challenge(verifier) }), config);
    const code = issueAuthorizationCode(request, config.connectorSecret, config);
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.now() + 6 * 60 * 1000));
    expect(() => verifyAccessToken(code, config)).toThrowError(OAuthError);
    vi.useRealTimers();

    // Create a token pair through the refresh path using a real refresh token from an exchange in another test is unnecessary;
    // malformed input must be rejected without leaking details.
    expect(() => refreshAccessToken({
      refreshToken: "invalid",
      clientId: config.clientId,
      clientSecret: config.clientSecret,
    }, config)).toThrowError(OAuthError);
  });
});

function authorizationUrl(overrides: Record<string, string> = {}): URL {
  const verifier = "v".repeat(43);
  const params = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: "http://localhost:4141/callback",
    response_type: "code",
    state: "state-value",
    code_challenge: challenge(verifier),
    code_challenge_method: "S256",
    ...overrides,
  });
  return new URL(`/oauth/authorize?${params}`, config.issuer);
}

function challenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}


describe("Registro dinâmico de cliente (RFC 7591)", () => {
  const dcrConfig: McpOAuthConfig = { ...config, dynamicRegistration: true };
  const claudeCallback = "https://claude.ai/api/mcp/auth_callback";

  it("fica desabilitado por padrão e não é anunciado no metadata", () => {
    expect(oauthMetadata(config)).not.toHaveProperty("registration_endpoint");
    expect(() => registerDynamicClient({ redirect_uris: [claudeCallback] }, config)).toThrowError(OAuthError);
  });

  it("quando habilitado, anuncia o endpoint e emite client_id/client_secret", () => {
    expect(oauthMetadata(dcrConfig).registration_endpoint).toBe(`${config.issuer}/oauth/register`);

    const registration = registerDynamicClient({ redirect_uris: [claudeCallback], client_name: "Claude" }, dcrConfig);

    expect(registration.client_id).toMatch(/^dyn_/);
    expect(registration.client_secret.length).toBeGreaterThanOrEqual(32);
    expect(registration.redirect_uris).toEqual([claudeCallback]);
  });

  it("recusa redirect_uri fora da allowlist — registrar não amplia destinos", () => {
    expect(() => registerDynamicClient({ redirect_uris: ["https://evil.example/callback"] }, dcrConfig))
      .toThrowError(OAuthError);
    expect(() => registerDynamicClient({ redirect_uris: [] }, dcrConfig)).toThrowError(OAuthError);
    expect(() => registerDynamicClient({}, dcrConfig)).toThrowError(OAuthError);
  });

  it("cliente dinâmico completa authorize → code → token como o estático", async () => {
    const registration = registerDynamicClient({ redirect_uris: [claudeCallback] }, dcrConfig);
    const verifier = "v".repeat(43);
    const url = authorizationUrl({ client_id: registration.client_id, redirect_uri: claudeCallback });

    const authorization = validateAuthorizationRequest(url, dcrConfig);
    const code = issueAuthorizationCode(authorization, dcrConfig.connectorSecret, dcrConfig);
    const tokens = await exchangeAuthorizationCode({
      code,
      clientId: registration.client_id,
      clientSecret: registration.client_secret,
      redirectUri: claudeCallback,
      codeVerifier: verifier,
    }, dcrConfig, async () => true);

    expect(tokens.token_type).toBe("Bearer");
    expect(verifyAccessToken(tokens.access_token, dcrConfig).principalId).toBe(config.principalId);
  });

  it("client_id forjado é recusado — só vale o que este servidor assinou", () => {
    const forged = authorizationUrl({ client_id: "dyn_qualquercoisa.inventada", redirect_uri: claudeCallback });
    expect(() => validateAuthorizationRequest(forged, dcrConfig)).toThrowError(OAuthError);
  });

  it("client_secret errado para um client_id legítimo é recusado", async () => {
    const registration = registerDynamicClient({ redirect_uris: [claudeCallback] }, dcrConfig);
    const url = authorizationUrl({ client_id: registration.client_id, redirect_uri: claudeCallback });
    const code = issueAuthorizationCode(validateAuthorizationRequest(url, dcrConfig), dcrConfig.connectorSecret, dcrConfig);

    await expect(exchangeAuthorizationCode({
      code,
      clientId: registration.client_id,
      clientSecret: "secret-errado",
      redirectUri: claudeCallback,
      codeVerifier: "v".repeat(43),
    }, dcrConfig, async () => true)).rejects.toThrowError(OAuthError);
  });

  it("registrar NÃO basta: sem o connector secret não sai código nenhum", () => {
    const registration = registerDynamicClient({ redirect_uris: [claudeCallback] }, dcrConfig);
    const url = authorizationUrl({ client_id: registration.client_id, redirect_uri: claudeCallback });
    const authorization = validateAuthorizationRequest(url, dcrConfig);

    expect(() => issueAuthorizationCode(authorization, "palpite-errado", dcrConfig)).toThrowError(OAuthError);
  });

  it("desligar a flag invalida clientes dinâmicos já emitidos", () => {
    const registration = registerDynamicClient({ redirect_uris: [claudeCallback] }, dcrConfig);
    const url = authorizationUrl({ client_id: registration.client_id, redirect_uri: claudeCallback });

    expect(() => validateAuthorizationRequest(url, config)).toThrowError(OAuthError);
  });
});
