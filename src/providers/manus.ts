import { z } from "zod";
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
  estimatedMaxCostUsd?: number;
}

const DEFAULT_BASE_URL = "https://api.manus.ai";
const DEFAULT_AGENT_PROFILE = "manus-1.6";
const DEFAULT_POLL_INTERVAL_MS = 3_000;
const DEFAULT_POLL_TIMEOUT_MS = 5 * 60_000;

const createTaskResponseSchema = z.object({
  ok: z.literal(true),
  request_id: z.string(),
  task_id: z.string(),
  task_title: z.string(),
  task_url: z.string(),
  share_url: z.string().optional(),
});

const taskDetailResponseSchema = z.object({
  ok: z.literal(true),
  request_id: z.string(),
  task: z.object({
    id: z.string(),
    status: z.enum(["running", "stopped", "waiting", "error"]),
    task_url: z.string().optional(),
    title: z.string().optional(),
    credit_usage: z.number().optional(),
  }),
});

const attachmentSchema = z.object({
  type: z.string().optional(),
  filename: z.string(),
  url: z.string(),
  content_type: z.string(),
});

const taskMessageSchema = z
  .object({
    id: z.string(),
    timestamp: z.number(),
    type: z.enum([
      "user_message",
      "assistant_message",
      "error_message",
      "status_update",
      "tool_used",
      "plan_update",
      "new_plan_step",
      "explanation",
      "user_stop",
      "structured_output_result",
    ]),
    assistant_message: z
      .object({ content: z.string(), attachments: z.array(attachmentSchema).optional() })
      .optional(),
    error_message: z.object({ error_type: z.string(), content: z.string() }).optional(),
    status_update: z
      .object({
        agent_status: z.enum(["running", "stopped", "waiting", "error"]),
        status_detail: z
          .object({
            waiting_for_event_id: z.string().optional(),
            waiting_for_event_type: z.string().optional(),
            waiting_description: z.string().optional(),
          })
          .passthrough()
          .optional(),
      })
      .passthrough()
      .optional(),
  })
  .passthrough();

const listMessagesResponseSchema = z.object({
  ok: z.literal(true),
  request_id: z.string(),
  task_id: z.string(),
  messages: z.array(taskMessageSchema),
  has_more: z.boolean(),
  next_cursor: z.string().optional(),
});

type CreateTaskResponse = z.infer<typeof createTaskResponseSchema>;
type TaskDetailResponse = z.infer<typeof taskDetailResponseSchema>;

export class ManusTaskWaitingError extends Error {
  constructor(public readonly taskId: string) {
    super(`Task Manus ${taskId} aguarda confirmação ou entrada do usuário.`);
    this.name = "ManusTaskWaitingError";
  }
}

/**
 * Provider Manus (FASE 2/14) — prioridade em investigação, pesquisa
 * profunda, execução autônoma sobre ferramentas (FASE 3).
 *
   * Contrato atualizado contra a documentação oficial v2 em 2026-08-17:
   * task.listMessages retorna eventos tipados (assistant_message,
   * status_update etc.) e paginação por cursor.
 */
export class ManusProvider implements AIProvider {
  readonly name = "manus" as const;
  readonly capabilities;
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
    this.capabilities = {
      mayProduceExternalEffects: true,
      estimatedMaxCostUsd: config.estimatedMaxCostUsd,
    } as const;
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
    const response = await fetchJson<unknown>(`${this.baseUrl}/v2/task.create`, {
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
    return createTaskResponseSchema.parse(response);
  }

  private async pollUntilDone(taskId: string): Promise<TaskDetailResponse> {
    const deadline = Date.now() + this.pollTimeoutMs;
    for (;;) {
      const response = await fetchJson<unknown>(
        `${this.baseUrl}/v2/task.detail?task_id=${encodeURIComponent(taskId)}`,
        { timeoutMs: this.timeoutMs, headers: { "x-manus-api-key": this.apiKey } },
      );
      const detail = taskDetailResponseSchema.parse(response);

      if (detail.task.status === "stopped" || detail.task.status === "error") {
        return detail;
      }
      if (detail.task.status === "waiting") {
        throw new ManusTaskWaitingError(taskId);
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
    let cursor: string | undefined;

    for (;;) {
      const params = new URLSearchParams({ task_id: taskId, order: "desc", limit: "200" });
      if (cursor) params.set("cursor", cursor);

      const response = await fetchJson<unknown>(`${this.baseUrl}/v2/task.listMessages?${params.toString()}`, {
        timeoutMs: this.timeoutMs,
        headers: { "x-manus-api-key": this.apiKey },
      });
      const list = listMessagesResponseSchema.parse(response);
      const assistant = list.messages.find(
        (message) => message.type === "assistant_message" && message.assistant_message?.content,
      );
      if (assistant?.assistant_message?.content) {
        return assistant.assistant_message.content;
      }

      if (!list.has_more || !list.next_cursor) {
        throw new Error(`Task Manus ${taskId} terminou sem evento assistant_message.`);
      }
      cursor = list.next_cursor;
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
