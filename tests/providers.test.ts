import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { AnthropicProvider } from "../src/providers/anthropic.js";
import { GeminiProvider } from "../src/providers/gemini.js";
import { ManusProvider, ManusTaskWaitingError } from "../src/providers/manus.js";
import { OpenAIProvider } from "../src/providers/openai.js";
import { ProviderHttpError, fetchJson, sanitizeUrlForLogs } from "../src/providers/httpClient.js";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("OpenAIProvider", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("usa Responses API com GPT-5.6 Terra no perfil balanceado e extrai output_text", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        output: [{ type: "message", content: [{ type: "output_text", text: "resposta do gpt" }] }],
        model: "gpt-5.6-sol",
        status: "completed",
      }),
    );

    const provider = new OpenAIProvider({ apiKey: "sk-test" });
    const result = await provider.analyze({ taskId: "t1", prompt: "oi" });

    expect(result.output).toBe("resposta do gpt");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.openai.com/v1/responses");
    expect(init.headers.authorization).toBe("Bearer sk-test");
    expect(JSON.parse(init.body)).toMatchObject({
      model: "gpt-5.6-terra",
      input: "oi",
      reasoning: { effort: "medium" },
    });
  });

  it("seleciona GPT-5.6 Sol para o perfil crítico", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ output: [], model: "gpt-5.6-sol", status: "completed" }),
    );
    const provider = new OpenAIProvider({ apiKey: "sk-test" });

    await provider.analyze({ taskId: "t2", prompt: "decida", modelProfile: "critical" });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).model).toBe("gpt-5.6-sol");
  });

  it("propaga erro HTTP como ProviderHttpError", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: "invalid key" } }, 401));
    const provider = new OpenAIProvider({ apiKey: "sk-bad" });
    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toBeInstanceOf(ProviderHttpError);
  });
});

describe("AnthropicProvider", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("envia o prompt com headers x-api-key/anthropic-version e junta blocos de texto", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ content: [{ type: "text", text: "parte 1" }, { type: "text", text: "parte 2" }], model: "claude-sonnet-5" }),
    );

    const provider = new AnthropicProvider({ apiKey: "ant-test" });
    const result = await provider.analyze({ taskId: "t1", prompt: "oi" });

    expect(result.output).toBe("parte 1\nparte 2");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.anthropic.com/v1/messages");
    expect(init.headers["x-api-key"]).toBe("ant-test");
    expect(init.headers["anthropic-version"]).toBe("2023-06-01");
  });

  it("rejeita resposta truncada por max_tokens", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        content: [{ type: "text", text: "resultado incompleto" }],
        model: "claude-sonnet-5",
        stop_reason: "max_tokens",
      }),
    );

    const provider = new AnthropicProvider({ apiKey: "ant-test", maxTokens: 32 });
    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toThrow(/truncada.*32/i);
  });

  it("seleciona Sonnet, Opus e Fable conforme o perfil", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ content: [], model: "claude-sonnet-5", stop_reason: "end_turn" }))
      .mockResolvedValueOnce(jsonResponse({ content: [], model: "claude-opus-5", stop_reason: "end_turn" }))
      .mockResolvedValueOnce(jsonResponse({ content: [], model: "claude-fable-5", stop_reason: "end_turn" }));
    const provider = new AnthropicProvider({ apiKey: "ant-test" });

    await provider.analyze({ taskId: "a1", prompt: "rotina", modelProfile: "balanced" });
    await provider.analyze({ taskId: "a2", prompt: "complexo", modelProfile: "critical" });
    await provider.analyze({ taskId: "a3", prompt: "adversarial", modelProfile: "adversarial" });

    expect(fetchMock.mock.calls.map((call) => JSON.parse(call[1].body).model)).toEqual([
      "claude-sonnet-5",
      "claude-opus-5",
      "claude-fable-5",
    ]);
  });
});

describe("GeminiProvider", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("chama generateContent com a key na query string e extrai o texto do primeiro candidate", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ candidates: [{ content: { parts: [{ text: "resposta gemini" }] } }] }),
    );

    const provider = new GeminiProvider({ apiKey: "gem-test" });
    const result = await provider.analyze({ taskId: "t1", prompt: "oi" });

    expect(result.output).toBe("resposta gemini");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("gemini-2.5-flash:generateContent?key=gem-test");
  });

  it("não inclui a API key da query string em erros", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: "quota" } }, 429));
    const provider = new GeminiProvider({ apiKey: "gem-secret-value" });

    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toMatchObject({
      message: expect.not.stringContaining("gem-secret-value"),
    });
  });
});

describe("sanitizeUrlForLogs", () => {
  it("remove query e fragmento sem perder o endpoint", () => {
    expect(sanitizeUrlForLogs("https://example.test/v1/models?key=secret#fragment")).toBe(
      "https://example.test/v1/models",
    );
  });
});

describe("ManusProvider", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("cria a task, faz poll e extrai assistant_message no schema oficial v2", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ok: true, request_id: "r1", task_id: "task-1", task_title: "t", task_url: "https://manus.im/t/task-1" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-1", status: "running" } }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r3", task: { id: "task-1", status: "stopped" } }))
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
          request_id: "r4",
          task_id: "task-1",
          messages: [
            { id: "m2", timestamp: 2, type: "assistant_message", assistant_message: { content: "achei a causa raiz" } },
            { id: "m1", timestamp: 1, type: "user_message", user_message: { content: "investigue isso" } },
          ],
          has_more: false,
        }),
      );

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    const result = await provider.analyze({ taskId: "t1", prompt: "investigue isso" });

    expect(result.output).toBe("achei a causa raiz");
    expect(result.sources).toEqual(["https://manus.im/t/task-1"]);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const [createUrl, createInit] = fetchMock.mock.calls[0];
    expect(createUrl).toBe("https://api.manus.ai/v2/task.create");
    expect(createInit.headers["x-manus-api-key"]).toBe("manus-test");
    expect(fetchMock.mock.calls[3][0]).toContain("order=desc&limit=200");
  });

  it("segue paginação por cursor até encontrar o assistant_message", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ok: true, request_id: "r1", task_id: "task-3", task_title: "t", task_url: "u" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-3", status: "stopped" } }))
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
          request_id: "r3",
          task_id: "task-3",
          messages: [{ id: "s1", timestamp: 3, type: "status_update", status_update: { agent_status: "stopped" } }],
          has_more: true,
          next_cursor: "cursor-2",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
          request_id: "r4",
          task_id: "task-3",
          messages: [{ id: "a1", timestamp: 2, type: "assistant_message", assistant_message: { content: "resultado paginado" } }],
          has_more: false,
        }),
      );

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    const result = await provider.analyze({ taskId: "t1", prompt: "x" });

    expect(result.output).toBe("resultado paginado");
    expect(fetchMock.mock.calls[3][0]).toContain("cursor=cursor-2");
  });

  it("interrompe em waiting sem confirmar automaticamente", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ok: true, request_id: "r1", task_id: "task-4", task_title: "t", task_url: "u" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-4", status: "waiting" } }));

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    await expect(provider.analyze({ taskId: "t1", prompt: "x" })).rejects.toBeInstanceOf(ManusTaskWaitingError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("rejeita fixture legado incompatível com o contrato oficial", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ok: true, request_id: "r1", task_id: "task-5", task_title: "t", task_url: "u" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-5", status: "stopped" } }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, messages: [{ role: "assistant", content: [] }] }));

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    await expect(provider.analyze({ taskId: "t1", prompt: "x" })).rejects.toBeInstanceOf(z.ZodError);
  });

  it("lança erro se a task terminar com status=error", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r1", task_id: "task-2", task_title: "t", task_url: "u" }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-2", status: "error" } }));

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    await expect(provider.analyze({ taskId: "t1", prompt: "x" })).rejects.toThrow(/status "error"/);
  });

  it("considera 401 do health check como credencial não saudável", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "unauthorized" }, 401));
    const provider = new ManusProvider({ apiKey: "manus-invalid" });

    const health = await provider.healthCheck();
    expect(health.healthy).toBe(false);
    expect(health.message).toBe("HTTP 401");
  });

  it("aceita 404 contratual do probe como endpoint saudável", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "task not found" }, 404));
    const provider = new ManusProvider({ apiKey: "manus-test" });

    const health = await provider.healthCheck();
    expect(health.healthy).toBe(true);
  });
});

describe("httpClient — retry/backoff (AU-8 da AGENT-AUDIT.md)", () => {
  const fetchMock = vi.fn();
  const noSleep = () => Promise.resolve();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("repete em 429 e devolve o sucesso da tentativa seguinte", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: "rate limited" }, 429))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const result = await fetchJson<{ ok: boolean }>("https://api.exemplo/x", { sleepFn: noSleep });

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("repete em 5xx na política safe (default)", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: "unavailable" }, 503))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    await fetchJson("https://api.exemplo/x", { sleepFn: noSleep });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("NUNCA repete 4xx que não seja 429 — erro do cliente, retry não corrige", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "invalid key" }, 401));

    await expect(fetchJson("https://api.exemplo/x", { sleepFn: noSleep })).rejects.toBeInstanceOf(ProviderHttpError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rate-limit-only: repete 429 mas NÃO repete 5xx (requisição não idempotente, ex. task.create do Manus)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "boom" }, 500));
    await expect(
      fetchJson("https://api.exemplo/x", { retryPolicy: "rate-limit-only", sleepFn: noSleep }),
    ).rejects.toBeInstanceOf(ProviderHttpError);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: "rate limited" }, 429))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    await fetchJson("https://api.exemplo/x", { retryPolicy: "rate-limit-only", sleepFn: noSleep });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("desiste após maxAttempts e propaga o último erro", async () => {
    // mockImplementation (não mockResolvedValue): cada tentativa precisa de um
    // Response novo, porque o body de um Response só pode ser lido uma vez.
    fetchMock.mockImplementation(async () => jsonResponse({ error: "unavailable" }, 503));

    await expect(fetchJson("https://api.exemplo/x", { maxAttempts: 3, sleepFn: noSleep })).rejects.toThrow(/HTTP 503/);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("respeita o header Retry-After quando presente", async () => {
    const delays: number[] = [];
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ error: "rate limited" }), {
          status: 429,
          headers: { "content-type": "application/json", "retry-after": "2" },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    await fetchJson("https://api.exemplo/x", {
      sleepFn: async (ms) => {
        delays.push(ms);
      },
    });

    expect(delays).toEqual([2000]);
  });
});

describe("usage e truncamento nos demais providers", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("Anthropic: captura usage real (tokens) — ausente vira undefined, nunca zero", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        content: [{ type: "text", text: "ok" }],
        model: "claude-sonnet-5",
        stop_reason: "end_turn",
        usage: { input_tokens: 120, output_tokens: 45 },
      }),
    );
    const provider = new AnthropicProvider({ apiKey: "ant-test" });
    const result = await provider.analyze({ taskId: "t1", prompt: "oi" });
    expect(result.usage).toEqual({ inputTokens: 120, outputTokens: 45 });
  });

  it("OpenAI (Responses API): usage é capturado no formato input/output_tokens", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        output: [{ type: "message", content: [{ type: "output_text", text: "ok" }] }],
        model: "gpt-5.6-terra",
        status: "completed",
        usage: { input_tokens: 10, output_tokens: 5 },
      }),
    );
    const provider = new OpenAIProvider({ apiKey: "sk-test" });
    const result = await provider.analyze({ taskId: "t2", prompt: "oi" });
    expect(result.usage).toEqual({ inputTokens: 10, outputTokens: 5 });
  });

  it("Gemini: finishReason=MAX_TOKENS vira erro; usageMetadata é capturado no caso normal", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ candidates: [{ content: { parts: [{ text: "cortad" }] }, finishReason: "MAX_TOKENS" }] }),
    );
    const provider = new GeminiProvider({ apiKey: "gem-test" });
    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toThrow(/MAX_TOKENS/);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        candidates: [{ content: { parts: [{ text: "ok" }] }, finishReason: "STOP" }],
        usageMetadata: { promptTokenCount: 8, candidatesTokenCount: 3 },
      }),
    );
    const result = await provider.analyze({ taskId: "t2", prompt: "oi" });
    expect(result.usage).toEqual({ inputTokens: 8, outputTokens: 3 });
  });
});
