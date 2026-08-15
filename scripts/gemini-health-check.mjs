// Teste pontual: valida só a GEMINI_API_KEY via healthCheck() (GET /models, sem custo).
// Uso: node --env-file=.env scripts/gemini-health-check.mjs
import { GeminiProvider } from "../dist/providers/gemini.js";

if (!process.env.GEMINI_API_KEY) {
  console.error("GEMINI_API_KEY não configurada no .env.");
  process.exit(1);
}

const provider = new GeminiProvider({
  apiKey: process.env.GEMINI_API_KEY,
  model: process.env.GEMINI_MODEL,
});

const status = await provider.healthCheck();
console.log(JSON.stringify(status, null, 2));
process.exitCode = status.healthy ? 0 : 1;
