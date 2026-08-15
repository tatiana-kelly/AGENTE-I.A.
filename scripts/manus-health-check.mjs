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
// process.exitCode em vez de process.exit(): chamar exit() logo após um fetch dispara um
// assertion crash conhecido do libuv no Node/Windows (handle de socket ainda fechando).
process.exitCode = status.healthy ? 0 : 1;
