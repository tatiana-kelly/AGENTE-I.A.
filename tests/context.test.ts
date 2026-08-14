import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { resolveContext } from "../src/orchestrator/contextResolver.js";

const FIXTURES_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "projects");

describe("resolveContext() — FASE 5", () => {
  it("retorna contexto vazio quando nenhum projeto é pedido (nunca carrega o repo inteiro)", async () => {
    const context = await resolveContext(undefined, FIXTURES_ROOT);
    expect(context).toEqual({ project: null, loaded: {}, missing: [] });
  });

  it("carrega só os arquivos que existem e reporta os que faltam, sem lançar erro", async () => {
    const context = await resolveContext("demo-project", FIXTURES_ROOT);

    expect(context.project).toBe("demo-project");
    expect(Object.keys(context.loaded).sort()).toEqual(["ARCHITECTURE.md", "PROJECT-CONTEXT.md"]);
    expect(context.loaded["PROJECT-CONTEXT.md"]).toContain("Fixture de teste");
    expect(context.missing.sort()).toEqual(["AI-INSTRUCTIONS.md", "BUSINESS-RULES.md", "DATA-DICTIONARY.md"]);
  });

  it("marca todos os 5 arquivos como missing quando o projeto não existe (sem lançar erro)", async () => {
    const context = await resolveContext("projeto-inexistente", FIXTURES_ROOT);
    expect(context.loaded).toEqual({});
    expect(context.missing).toHaveLength(5);
  });

  it("rejeita nomes de projeto fora de [a-zA-Z0-9_-] (proteção contra path traversal)", async () => {
    await expect(resolveContext("../../etc", FIXTURES_ROOT)).rejects.toThrow(/Nome de projeto inválido/);
    await expect(resolveContext("demo project", FIXTURES_ROOT)).rejects.toThrow(/Nome de projeto inválido/);
  });
});
