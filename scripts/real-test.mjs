// FASE 19 — teste real de baixo risco, sempre em READ_ONLY. Não altera nada.
// Uso: node --env-file=.env scripts/real-test.mjs
import { buildProviderManagerFromEnv } from "../dist/providers/index.js";
import { orchestrate } from "../dist/orchestrator/index.js";

const { manager, registered, skipped } = buildProviderManagerFromEnv();
console.error("providers registrados:", registered, "| não configurados:", skipped);

const task =
  process.argv[2] ??
  "Este código implementa uma automação (o AI Orchestrator do SAL AI OS). " +
    "Sem alterar nada, analise a automação e aponte os 5 maiores riscos técnicos atuais.";

const result = await orchestrate(
  { task },
  { security: { mode: "READ_ONLY", dryRun: true }, providerManager: manager },
);

console.log(JSON.stringify(result, null, 2));
