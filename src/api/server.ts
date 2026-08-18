import { createServer } from "node:http";
import { createApiHandler } from "./app.js";
import { buildProviderManagerFromEnv } from "../providers/index.js";
import { buildSupabaseRepositoryFromEnv } from "../persistence/index.js";

const repository = buildSupabaseRepositoryFromEnv();
if (!repository) throw new Error("A API exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");

const webhookSecret = process.env.N8N_WEBHOOK_SECRET?.trim();
if (!webhookSecret) throw new Error("N8N_WEBHOOK_SECRET não configurado.");

const { manager } = buildProviderManagerFromEnv();
const handler = createApiHandler({ repository, providerManager: manager, webhookSecret });
const server = createServer((request, response) => void handler(request, response));
server.requestTimeout = 310_000;
server.headersTimeout = 15_000;
server.keepAliveTimeout = 5_000;

const port = parsePort(process.env.PORT);
server.listen(port, "0.0.0.0", () => {
  console.log(JSON.stringify({ service: "ai-orchestrator", status: "listening", port }));
});

function parsePort(value: string | undefined): number {
  const parsed = Number(value ?? 3000);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) throw new Error("PORT inválida.");
  return parsed;
}
