import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { AnthropicProvider } from "../src/providers/anthropic.js";
import { GeminiProvider } from "../src/providers/gemini.js";
import { ManusProvider, ManusTaskWaitingError } from "../src/providers/manus.js";
import { OpenAIProvider } from "../src/providers/openai.js";
import { ProviderHttpError } from "../src/providers/httpClient.js";

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

  it("envia o prompt e extrai o texto da resposta", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ choices: [{ message: { content: "resposta do gpt" }, finish_reason: "stop" }], model: "gpt-4o-mini" }),
    );

    const provider = new OpenAIProvider({ apiKey: "sk-test" });
    const result = await provider.analyze({ taskId: "t1", prompt: "oi" });

    expect(result.output).toBe("resposta do gpt");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.openai.com/v1/chat/completions");
    expect(init.headers.authorization).toBe("Bearer sk-test");
    expect(JSON.parse(init.body).messages[0].content).toBe("oi");
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

  it("lança erro claro quando a resposta é truncada por max_tokens — nunca entrega output parcial (porta do fix a6e1440)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        content: [{ type: "text", text: "resposta cortada no mei" }],
        model: "claude-sonnet-5",
        stop_reason: "max_tokens",
      }),
    );

    const provider = new AnthropicProvider({ apiKey: "ant-test" });
    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toThrow(/truncada por max_tokens/);
  });

  it("captura usage real (tokens) reportado pela API — ausente vira undefined, nunca zero", async () => {
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
});

describe("truncamento e usage nos demais providers (mesma classe de bug do fix a6e1440)", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("OpenAI: finish_reason=length vira erro; usage é capturado no caso normal", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ choices: [{ message: { content: "cortad" }, finish_reason: "length" }], model: "gpt-4o-mini" }),
    );
    const provider = new OpenAIProvider({ apiKey: "sk-test" });
    await expect(provider.analyze({ taskId: "t1", prompt: "oi" })).rejects.toThrow(/finish_reason=length/);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        choices: [{ message: { content: "ok" }, finish_reason: "stop" }],
        model: "gpt-4o-mini",
        usage: { prompt_tokens: 10, completion_tokens: 5 },
      }),
    );
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
});
