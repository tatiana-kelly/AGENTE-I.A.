import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { orchestrate } from "../src/orchestrator/index.js";
import { ProviderManager } from "../src/orchestrator/providerManager.js";
import { InMemoryEvidenceSink } from "../src/orchestrator/evidenceManager.js";
import type { AIProvider, HealthStatus, TaskInput, TaskResult } from "../src/providers/types.js";

const FIXTURES_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "projects");

class FakeProvider implements AIProvider {
  readonly capabilities = { mayProduceExternalEffects: false } as const;
  readonly inputs: TaskInput[] = [];

  constructor(
    readonly name: AIProvider["name"],
    private readonly output: string,
  ) {}

  async analyze(input: TaskInput): Promise<TaskResult> {
    this.inputs.push(input);
    return { output: this.output, sources: [`fake://${this.name}`], evidence: [], confidence: 0.9 };
  }

  async healthCheck(): Promise<HealthStatus> {
    return { healthy: true, checkedAt: new Date().toISOString() };
  }
}

class AgenticFakeProvider extends FakeProvider {
  override readonly capabilities = { mayProduceExternalEffects: true } as const;
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

  it("bloqueia falso negativo de escrita em READ_ONLY antes de chamar provider", async () => {
    const manager = new ProviderManager();
    const provider = new FakeProvider("manus", "não deveria rodar");
    manager.register(provider);

    const result = await orchestrate(
      { task: "Altere o arquivo de configuração, remova a regra antiga e faça o deploy." },
      { security: { mode: "READ_ONLY", dryRun: true }, providerManager: manager },
    );

    expect(result.classification.effectLevel).toBe("EXTERNAL_ACTION");
    expect(result.requiresApproval).toBe(true);
    expect(result.results).toEqual([]);
  });

  it("bloqueia efeito desconhecido por padrão, inclusive em AUTONOMOUS", async () => {
    const result = await orchestrate(
      { task: "Cuide disso para mim." },
      { security: { mode: "AUTONOMOUS", dryRun: false } },
    );

    expect(result.classification.effectLevel).toBe("UNKNOWN");
    expect(result.requiresApproval).toBe(true);
    expect(result.results).toEqual([]);
  });

  it("bloqueia provider agente em READ_ONLY mesmo quando o prompt parece leitura", async () => {
    const manager = new ProviderManager();
    manager.register(new AgenticFakeProvider("manus", "não deveria rodar"));

    const result = await orchestrate(
      { task: "Investigue profundamente esse problema." },
      { security: { mode: "READ_ONLY", dryRun: true }, providerManager: manager },
    );

    expect(result.results[0]).toMatchObject({ provider: "manus", status: "skipped" });
    expect(result.results[0]?.reason).toMatch(/READ_ONLY/);
    expect(result.evidence).toEqual([]);
  });

  it("interrompe a cadeia quando um step obrigatório não está registrado", async () => {
    const manager = new ProviderManager();
    manager.register(new FakeProvider("openai", "decisão tomada"));
    // "manus" não registrado — o plano de "Pesquise e depois tome uma decisão." pede manus → openai.

    const result = await orchestrate(
      { task: "Pesquise e depois tome uma decisão." },
      { security: { mode: "AUTONOMOUS", dryRun: false }, providerManager: manager },
    );

    expect(result.plan.mode).toBe("MULTI_AGENT");
    expect(result.results[0]).toMatchObject({ provider: "manus", status: "skipped" });
    expect(result.results).toHaveLength(1);
  });

  it("propaga contexto do projeto e saída anterior para o próximo step", async () => {
    const manager = new ProviderManager();
    const manus = new FakeProvider("manus", "causa raiz identificada");
    const openai = new FakeProvider("openai", "decisão baseada na causa raiz");
    manager.register(manus);
    manager.register(openai);

    const result = await orchestrate(
      { task: "Pesquise e depois tome uma decisão.", project: "demo-project" },
      {
        security: { mode: "AUTONOMOUS", dryRun: false },
        providerManager: manager,
        projectsRoot: FIXTURES_ROOT,
      },
    );

    expect(result.results.map(({ provider, status }) => ({ provider, status }))).toEqual([
      { provider: "manus", status: "success" },
      { provider: "openai", status: "success" },
    ]);
    expect(manus.inputs[0]?.context).toMatchObject({
      projectFiles: { "PROJECT-CONTEXT.md": expect.stringContaining("Fixture de teste") },
      previousResults: [],
    });
    expect(openai.inputs[0]?.prompt).toContain("causa raiz identificada");
    expect(openai.inputs[0]?.prompt).toContain("tomar a decisão");
    expect(openai.inputs[0]?.context).toMatchObject({
      previousResults: [{ provider: "manus", output: "causa raiz identificada" }],
    });
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
