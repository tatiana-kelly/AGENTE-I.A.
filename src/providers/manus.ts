import { ProviderHttpError, describeProviderError, fetchJson } from "./httpClient.js";
import type { AIProvider, HealthStatus, TaskInput, TaskResult } from "./types.js";

export interface ManusProviderConfig {
  apiKey: string;
  baseUrl?: string;
  /** manus-1.6 | manus-1.6-lite | manus-1.6-max — ver doc oficial. */
  agentProfile?: string;
  timeoutMs?: number;
  pollIntervalMs?: number;
  pollTimeoutMs?: number;
}

const DEFAULT_BASE_URL = "https://api.manus.ai";
const DEFAULT_AGENT_PROFILE = "manus-1.6";
const DEFAULT_POLL_INTERVAL_MS = 3_000;
const DEFAULT_POLL_TIMEOUT_MS = 5 * 60_000;

interface CreateTaskResponse {
  ok: boolean;
  request_id: string;
  task_id: string;
  task_title: string;
  task_url: string;
  share_url?: string;
}

interface TaskDetailResponse {
  ok: boolean;
  request_id: string;
  task: {
    id: string;
    status: "running" | "stopped" | "waiting" | "error";
    task_url: string;
    title: string;
  };
}

interface TaskMessage {
  role: string;
  content: Array<{ type: string; text?: string }>;
}

interface ListMessagesResponse {
  ok: boolean;
  messages: TaskMessage[];
}

/**
 * Provider Manus (FASE 2/14) — prioridade em investigação, pesquisa
 * profunda, execução autônoma sobre ferramentas (FASE 3).
 *
 * Verificado contra a API v2 oficial em 2026-08-13
 * (open.manus.im/docs/api-reference/create-task e /get-task — PRP exige
 * explicitamente não usar API deprecated; v1 está deprecated, v2 é a
 * vigente). `POST /v2/task.create` e `GET /v2/task.detail` foram
 * confirmados na doc. O endpoint `task.listMessages` usado abaixo é
 * citado por nome na doc de `task.detail` ("Use task.listMessages for
 * full conversation history") mas seu schema de resposta não pôde ser
 * confirmado nesta sessão — **validar a forma exata de `messages[]`
 * contra uma chamada real antes de depender disso em produção.**
 */
export class ManusProvider implements AIProvider {
  readonly name = "manus" as const;
  readonly capabilities = { mayProduceExternalEffects: true } as const;
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly agentProfile: string;
  private readonly timeoutMs?: number;
  private readonly pollIntervalMs: number;
  private readonly pollTimeoutMs: number;

  constructor(config: ManusProviderConfig) {
    if (!config.apiKey) {
      throw new Error("ManusProvider requer apiKey (MANUS_API_KEY).");
    }
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    this.agentProfile = config.agentProfile ?? DEFAULT_AGENT_PROFILE;
    this.timeoutMs = config.timeoutMs;
    this.pollIntervalMs = config.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
    this.pollTimeoutMs = config.pollTimeoutMs ?? DEFAULT_POLL_TIMEOUT_MS;
  }

  async analyze(input: TaskInput): Promise<TaskResult> {
    const created = await this.createTask(input.prompt);
    const finalDetail = await this.pollUntilDone(created.task_id);

    if (finalDetail.task.status === "error") {
      throw new Error(`Task Manus ${created.task_id} terminou com status "error".`);
    }

    const output = await this.getFinalOutput(created.task_id);

    return {
      output,
      sources: [created.task_url],
      evidence: [created.task_id],
      raw: { created, finalDetail },
    };
  }

  async healthCheck(): Promise<HealthStatus> {
    // Não há endpoint de health dedicado documentado — usamos task.detail
    // com um task_id inexistente. Um 4xx estruturado prova que a API key
    // e o endpoint respondem; só um erro de rede/timeout conta como
    // "unhealthy" de fato.
    const checkedAt = new Date().toISOString();
    const start = performance.now();
    try {
      await fetchJson(`${this.baseUrl}/v2/task.detail?task_id=health-check-probe`, {
        timeoutMs: this.timeoutMs ?? 10_000,
        headers: { "x-manus-api-key": this.apiKey },
      });
      return { healthy: true, latencyMs: performance.now() - start, checkedAt };
    } catch (error) {
      if (error instanceof ProviderHttpError && error.status < 500) {
        return {
          healthy: true,
          latencyMs: performance.now() - start,
          checkedAt,
          message: "API respondeu (probe com task_id inválido, 4xx esperado)",
        };
      }
      return { healthy: false, latencyMs: performance.now() - start, message: describeProviderError(error), checkedAt };
    }
  }

  private async createTask(prompt: string): Promise<CreateTaskResponse> {
    return fetchJson<CreateTaskResponse>(`${this.baseUrl}/v2/task.create`, {
      method: "POST",
      timeoutMs: this.timeoutMs,
      headers: {
        "content-type": "application/json",
        "x-manus-api-key": this.apiKey,
      },
      body: JSON.stringify({
        message: { content: [{ type: "text", text: prompt }] },
        agent_profile: this.agentProfile,
      }),
    });
  }

  private async pollUntilDone(taskId: string): Promise<TaskDetailResponse> {
    const deadline = Date.now() + this.pollTimeoutMs;
    for (;;) {
      const detail = await fetchJson<TaskDetailResponse>(
        `${this.baseUrl}/v2/task.detail?task_id=${encodeURIComponent(taskId)}`,
        { timeoutMs: this.timeoutMs, headers: { "x-manus-api-key": this.apiKey } },
      );

      if (detail.task.status === "stopped" || detail.task.status === "error") {
        return detail;
      }
      if (Date.now() > deadline) {
        throw new Error(
          `Task Manus ${taskId} não terminou dentro de ${this.pollTimeoutMs}ms (status atual: ${detail.task.status}).`,
        );
      }
      await sleep(this.pollIntervalMs);
    }
  }

  private async getFinalOutput(taskId: string): Promise<string> {
    const list = await fetchJson<ListMessagesResponse>(
      `${this.baseUrl}/v2/task.listMessages?task_id=${encodeURIComponent(taskId)}`,
      { timeoutMs: this.timeoutMs, headers: { "x-manus-api-key": this.apiKey } },
    );

    const lastAssistantMessage = [...list.messages].reverse().find((message) => message.role === "assistant");
    if (!lastAssistantMessage) {
      return "";
    }

    return lastAssistantMessage.content
      .filter((block) => block.type === "text" && block.text)
      .map((block) => block.text)
      .join("\n");
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
