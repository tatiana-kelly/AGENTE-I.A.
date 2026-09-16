// Roda uma tarefa real do Orchestrator sobre um projeto integrado.
//
//   node --env-file=.env scripts/run-task.mjs <projeto> "<tarefa>" [--assisted]
//
// Padrão READ_ONLY + DRY_RUN: nada é alterado. `--assisted` só libera o gate
// para tarefas de escrita quando a pessoa já autorizou — continua exigindo
// aprovação explícita no caminho do orchestrator.
//
// Chaves vêm SÓ do ambiente. O teto de custo por chamada é obrigatório: sem
// ele o Cost Controller bloqueia o provider antes de gerar qualquer gasto.
import { OpenAIProvider, AnthropicProvider, GeminiProvider, ManusProvider } from "../dist/providers/index.js";
import { ProviderManager } from "../dist/orchestrator/providerManager.js";
import { orchestrate } from "../dist/orchestrator/index.js";

const [project, task, ...flags] = process.argv.slice(2);
if (!project || !task) {
  console.error('Uso: node --env-file=.env scripts/run-task.mjs <projeto> "<tarefa>" [--assisted]');
  process.exit(1);
}

const maxCostUsd = Number(process.env.MAX_COST_PER_CALL_USD ?? "0.30");
// 30s (default do cliente HTTP) não cobre análise com contexto de projeto inteiro.
// Timeout não é repetido pelo retry — de propósito: repetir tende a estourar de novo.
const timeoutMs = Number(process.env.TASK_TIMEOUT_MS ?? "180000");
// 4096 (default) trunca análise executiva com contexto de projeto — e a resposta
// cortada é REJEITADA, nunca entregue pela metade. Espaço proporcional à tarefa.
const maxOutputTokens = Number(process.env.TASK_MAX_OUTPUT_TOKENS ?? "16000");
const manager = new ProviderManager();
const registrados = [];
if (process.env.OPENAI_API_KEY) {
  manager.register(new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY, estimatedMaxCostUsd: maxCostUsd, timeoutMs, maxOutputTokens }));
  registrados.push("openai");
}
if (process.env.ANTHROPIC_API_KEY) {
  manager.register(new AnthropicProvider({ apiKey: process.env.ANTHROPIC_API_KEY, estimatedMaxCostUsd: maxCostUsd, timeoutMs, maxOutputTokens }));
  registrados.push("anthropic");
}
if (process.env.GEMINI_API_KEY) {
  manager.register(new GeminiProvider({ apiKey: process.env.GEMINI_API_KEY, estimatedMaxCostUsd: maxCostUsd, timeoutMs, maxOutputTokens }));
  registrados.push("gemini");
}
if (process.env.MANUS_API_KEY) {
  manager.register(new ManusProvider({ apiKey: process.env.MANUS_API_KEY, estimatedMaxCostUsd: maxCostUsd, timeoutMs, maxOutputTokens }));
  registrados.push("manus");
}

const mode = flags.includes("--assisted") ? "ASSISTED" : "READ_ONLY";
console.error(`projeto: ${project} | modo: ${mode} | teto: US$${maxCostUsd}/chamada | providers: ${registrados.join(", ")}`);

const result = await orchestrate(
  { task, project },
  { security: { mode, dryRun: false }, providerManager: manager, repository: null },
);

const executados = result.results.filter((r) => r.status === "success");
console.error(
  "\n" +
    JSON.stringify(
      {
        taskId: result.taskId,
        efeito: result.classification.effectLevel,
        skills: result.classification.skills,
        contexto: `${Object.keys(result.context.loaded).length} arquivos, faltando: ${result.context.missing.length}`,
        rota: `${result.routing.primary}${result.routing.reviewer ? ` → revisão ${result.routing.reviewer}` : ""}`,
        passos: result.results.map((r) => `${r.provider}: ${r.status}${r.reason ? ` (${r.reason})` : ""}`),
        revisao: result.validation && `${result.validation.status} — ${result.validation.summary}`,
        correcoes: result.validation?.corrections?.length ?? 0,
        precisaAprovacao: result.requiresApproval,
      },
      null,
      2,
    ),
);

console.log(executados.length ? executados.at(-1).output : "(nenhum provider executou — ver passos acima)");
