import { describe, expect, it } from "vitest";
import { orchestrate } from "../src/orchestrator/index.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryEvidenceSink } from "../src/orchestrator/evidenceManager.js";
import type { AIProvider, HealthStatus, TaskInput, TaskResult } from "../src/providers/types.js";

class FakeProvider implements AIProvider {
  constructor(
    readonly name: AIProvider["name"],
    private readonly output: string,
  ) {}

  async analyze(_input: TaskInput): Promise<TaskResult> {
    return { output: this.output, sources: [`fake://${this.name}`], evidence: [], confidence: 0.9 };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: new Date().toISOString() };
  }
}

describe("orchestrate() — execução ponta a ponta", () => {
  it("executa uma tarefa de leitura (investigação) mesmo em READ_ONLY e registra evidência", async () => {
    const manager = new ProviderManager();
    manager.register(new FakeProvider("manus", "achei a causa raiz"));
    manager.register(new FakeProvider("openai", "confirmado, faz sentido"));
    const evidenceSink = new InMemoryEvidenceSink();

    const result = await orchestrate(
      { task: "Descubra por que esse indicador caiu." },
      { security: { mode: "READ_ONLY", dryRun: true }, providerManager: manager, evidenceSink },
    );

    expect(result.requiresApproval).toBe(false);
    expect(result.results).toEqual([{ provider: "manus", purpose: expect.any(String), status: "success", output: "achei a causa raiz" }]);
    expect(result.evidence).toHaveLength(1);
    expect(evidenceSink.list()).toHaveLength(1);
  });

  it("bloqueia uma tarefa de implementação (escrita) em READ_ONLY sem chamar nenhum provider", async () => {
    const manager = new ProviderManager();
    manager.register(new FakeProvider("anthropic", "não deveria rodar"));

    const result = await orchestrate(
      { task: "Implemente essa arquitetura." },
      { security: { mode: "READ_ONLY", dryRun: true }, providerManager: manager },
    );

    expect(result.requiresApproval).toBe(true);
    expect(result.results).toEqual([]);
    expect(result.evidence).toEqual([]);
  });

  it("marca como skipped (sem lançar erro) um step cujo provider não está registrado", async () => {
    const manager = new ProviderManager();
    manager.register(new FakeProvider("openai", "decisão tomada"));
    // "manus" não registrado — o plano de "Pesquise e depois tome uma decisão." pede manus → openai.

    const result = await orchestrate(
      { task: "Pesquise e depois tome uma decisão." },
      { security: { mode: "AUTONOMOUS", dryRun: false }, providerManager: manager },
    );

    expect(result.plan.mode).toBe("MULTI_AGENT");
    expect(result.results[0]).toMatchObject({ provider: "manus", status: "skipped" });
    expect(result.results[1]).toMatchObject({ provider: "openai", status: "success" });
  });

  it("roda a cadeia de validação (reviewer) quando a routing decision atribui um", async () => {
    const manager = new ProviderManager();
    manager.register(new FakeProvider("manus", "achei o motivo"));
    manager.register(new FakeProvider("openai", "revisão: faz sentido do ponto de vista de negócio"));

    const result = await orchestrate(
      { task: "Analise os dados e me diga o que está acontecendo." },
      { security: { mode: "AUTONOMOUS", dryRun: false }, providerManager: manager },
    );

    expect(result.routing.reviewer).toBe("openai");
    expect(result.validation).toMatchObject({ reviewed: true, reviewer: "openai" });
    expect(result.evidence).toHaveLength(2); // resultado primário + revisão
  });

  it("continua sem erro quando nenhum provider está registrado (dry-run total)", async () => {
    const result = await orchestrate(
      { task: "Corrija esse bug." },
      { security: { mode: "AUTONOMOUS", dryRun: false } },
    );

    expect(result.results[0]).toMatchObject({ provider: "anthropic", status: "skipped" });
  });
});
