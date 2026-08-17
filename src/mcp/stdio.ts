import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { buildSupabaseRepositoryFromEnv, type ProjectPrincipalType } from "../persistence/index.js";
import { createProjectMcpServer } from "./server.js";

const repository = buildSupabaseRepositoryFromEnv();
if (!repository) throw new Error("MCP exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");

const principalId = process.env.MCP_PRINCIPAL_ID?.trim();
if (!principalId) throw new Error("MCP_PRINCIPAL_ID não configurado.");
const principalType = parsePrincipalType(process.env.MCP_PRINCIPAL_TYPE);

const server = createProjectMcpServer({ repository, principal: { type: principalType, id: principalId } });
await server.connect(new StdioServerTransport());

function parsePrincipalType(value: string | undefined): ProjectPrincipalType {
  if (value === "user" || value === "service" || value === "agent") return value;
  throw new Error("MCP_PRINCIPAL_TYPE deve ser user, service ou agent.");
}
