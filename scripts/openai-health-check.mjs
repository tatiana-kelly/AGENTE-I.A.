// Teste pontual: valida só a OPENAI_API_KEY via healthCheck() (GET /models, sem custo).
// Uso: node --env-file=.env scripts/openai-health-check.mjs
import { OpenAIProvider } from "../dist/providers/openai.js";

if (!process.env.OPENAI_API_KEY) {
  console.error("OPENAI_API_KEY não configurada no .env.");
  process.exit(1);
}

const provider = new OpenAIProvider({
  apiKey: process.env.OPENAI_API_KEY,
  model: process.env.OPENAI_MODEL,
});

const status = await provider.healthCheck();
console.log(JSON.stringify(status, null, 2));
// process.exitCode em vez de process.exit(): chamar exit() logo após um fetch dispara um
// assertion crash conhecido do libuv no Node/Windows (handle de socket ainda fechando).
process.exitCode = status.healthy ? 0 : 1;
