// Teste pontual: valida só a MANUS_API_KEY via healthCheck() (sem criar task, sem custo).
// Uso: node --env-file=.env scripts/manus-health-check.mjs
import { ManusProvider } from "../dist/providers/manus.js";

if (!process.env.MANUS_API_KEY) {
  console.error("MANUS_API_KEY não configurada no .env.");
  process.exit(1);
}

const provider = new ManusProvider({
  apiKey: process.env.MANUS_API_KEY,
  agentProfile: process.env.MANUS_AGENT_PROFILE,
});

const status = await provider.healthCheck();
console.log(JSON.stringify(status, null, 2));
process.exit(status.healthy ? 0 : 1);
