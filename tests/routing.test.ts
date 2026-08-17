import { describe, expect, it } from "vitest";
import { classifyTask } from "../src/orchestrator/taskClassifier.js";
import { routeTask } from "../src/orchestrator/routingEngine.js";
import { planTask } from "../src/orchestrator/taskPlanner.js";

function decide(task: string) {
  const classification = classifyTask(task);
  const routing = routeTask(classification);
  const plan = planTask(classification, routing);
  return { classification, routing, plan };
}

// FASE 18 — casos de teste de routing definidos no próprio PRP-003.
describe("FASE 18 — routing examples", () => {
  it('"Me ajude a tomar uma decisão estratégica." → OPENAI', () => {
    expect(decide("Me ajude a tomar uma decisão estratégica.").routing.primary).toBe("openai");
  });

  it('"Investigue profundamente esse problema." → MANUS', () => {
    expect(decide("Investigue profundamente esse problema.").routing.primary).toBe("manus");
  });

  it('"Descubra por que esse indicador caiu." → MANUS', () => {
    const { routing } = decide("Descubra por que esse indicador caiu.");
    expect(routing.primary).toBe("manus");
    expect(routing.reviewer).toBeUndefined();
  });

  it('"Analise os dados e me diga o que está acontecendo." → MANUS + OPENAI', () => {
    const { routing } = decide("Analise os dados e me diga o que está acontecendo.");
    expect(routing.primary).toBe("manus");
    expect(routing.reviewer).toBe("openai");
  });

  it('"Crie a arquitetura desse sistema." → OPENAI', () => {
    expect(decide("Crie a arquitetura desse sistema.").routing.primary).toBe("openai");
  });

  it('"Implemente essa arquitetura." → CLAUDE CODE', () => {
    expect(decide("Implemente essa arquitetura.").routing.primary).toBe("anthropic");
  });

  it('"Corrija esse bug." → CLAUDE CODE', () => {
    expect(decide("Corrija esse bug.").routing.primary).toBe("anthropic");
  });

  it('"Analise minha planilha do Google." → GEMINI', () => {
    expect(decide("Analise minha planilha do Google.").routing.primary).toBe("gemini");
  });

  it('"Pesquise e depois tome uma decisão." → MANUS → OPENAI (multi-agent)', () => {
    const { plan } = decide("Pesquise e depois tome uma decisão.");
    expect(plan.mode).toBe("MULTI_AGENT");
    expect(plan.steps.map((step) => step.provider)).toEqual(["manus", "openai"]);
  });
});

// DEFINIÇÃO DE SUCESSO do PRP-003 — exemplo citado literalmente no documento.
describe("Definição de sucesso do PRP-003", () => {
  it('"Descubra por que o custo de transferência aumentou." → manus (reviewer openai)', () => {
    const { routing } = decide("Descubra por que o custo de transferência aumentou.");
    expect(routing.primary).toBe("manus");
    expect(routing.reviewer).toBe("openai");
  });

  it('"Implemente a solução encontrada." → Claude Code', () => {
    expect(decide("Implemente a solução encontrada.").routing.primary).toBe("anthropic");
  });

  it('"Valide se a solução faz sentido para o negócio." → OpenAI', () => {
    expect(decide("Valide se a solução faz sentido para o negócio.").routing.primary).toBe("openai");
  });
});

describe("classificação de efeitos — fail-closed", () => {
  it("classifica análise sobre implementação como leitura, sem falso positivo de escrita", () => {
    const { classification } = decide("Analise como implementar esta arquitetura e indique os riscos.");
    expect(classification.effectLevel).toBe("READ");
    expect(classification.requiresImplementation).toBe(false);
  });

  it("classifica alteração/deploy como ação externa", () => {
    const { classification } = decide("Altere o arquivo de configuração, remova a regra antiga e faça o deploy.");
    expect(classification.effectLevel).toBe("EXTERNAL_ACTION");
  });

  it("classifica envio de email e atualização de planilha como efeitos bloqueáveis", () => {
    expect(decide("Envie o relatório por email.").classification.effectLevel).toBe("EXTERNAL_ACTION");
    expect(decide("Atualize a planilha de custos.").classification.effectLevel).toBe("WRITE");
  });

  it("trata tarefa sem intenção reconhecida como UNKNOWN", () => {
    expect(decide("Cuide disso para mim.").classification.effectLevel).toBe("UNKNOWN");
  });
});
