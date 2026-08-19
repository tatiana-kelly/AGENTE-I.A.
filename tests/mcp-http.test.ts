import { createServer } from "node:http";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createMcpHttpHandler } from "../src/mcp/http.js";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";

const envNames = [
  "MCP_OAUTH_ISSUER",
  "MCP_OAUTH_CLIENT_ID",
  "MCP_OAUTH_CLIENT_SECRET",
  "MCP_CONNECTOR_SECRET",
  "MCP_TOKEN_SIGNING_SECRET",
  "MCP_PRINCIPAL_ID",
] as const;
const previous = new Map<string, string | undefined>();

beforeEach(() => {
  for (const name of envNames) previous.set(name, process.env[name]);
  process.env.MCP_OAUTH_CLIENT_ID = "sal-claude";
  process.env.MCP_OAUTH_CLIENT_SECRET = "c".repeat(32);
  process.env.MCP_CONNECTOR_SECRET = "a".repeat(32);
  process.env.MCP_TOKEN_SIGNING_SECRET = "s".repeat(32);
  process.env.MCP_PRINCIPAL_ID = "claude";
});

afterEach(() => {
  for (const [name, value] of previous) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

describe("remote MCP HTTP", () => {
  it("publica discovery OAuth e aponta o recurso MCP exato", async () => {
    await withServer(async (origin) => {
      process.env.MCP_OAUTH_ISSUER = origin;
      const authorization = await fetch(`${origin}/.well-known/oauth-authorization-server`).then((response) => response.json()) as Record<string, unknown>;
      const resource = await fetch(`${origin}/.well-known/oauth-protected-resource/mcp`).then((response) => response.json()) as Record<string, unknown>;
      expect(authorization.authorization_endpoint).toBe(`${origin}/oauth/authorize`);
      expect(resource.resource).toBe(`${origin}/mcp`);
      expect(resource).not.toHaveProperty("client_secret");
    });
  });

  it("responde 401 com resource_metadata quando não há access token", async () => {
    await withServer(async (origin) => {
      process.env.MCP_OAUTH_ISSUER = origin;
      const response = await fetch(`${origin}/mcp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
      });
      expect(response.status).toBe(401);
      expect(response.headers.get("www-authenticate")).toContain("oauth-protected-resource/mcp");
    });
  });
});

async function withServer(run: (origin: string) => Promise<void>): Promise<void> {
  const handler = createMcpHttpHandler({
    repository: new InMemoryOrchestrationRepository(),
    providerManager: new ProviderManager(),
  });
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Test server sem porta.");
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}
