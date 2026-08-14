import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "../src/providers/anthropic.js";
import { GeminiProvider } from "../src/providers/gemini.js";
import { ManusProvider } from "../src/providers/manus.js";
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

  it("cria a task, faz poll até status=stopped e busca a última mensagem do assistant", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ ok: true, request_id: "r1", task_id: "task-1", task_title: "t", task_url: "https://manus.im/t/task-1" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-1", status: "running" } }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r3", task: { id: "task-1", status: "stopped" } }))
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
          messages: [
            { role: "user", content: [{ type: "text", text: "investigue isso" }] },
            { role: "assistant", content: [{ type: "text", text: "achei a causa raiz" }] },
          ],
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
  });

  it("lança erro se a task terminar com status=error", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r1", task_id: "task-2", task_title: "t", task_url: "u" }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, request_id: "r2", task: { id: "task-2", status: "error" } }));

    const provider = new ManusProvider({ apiKey: "manus-test", pollIntervalMs: 1 });
    await expect(provider.analyze({ taskId: "t1", prompt: "x" })).rejects.toThrow(/status "error"/);
  });
});
