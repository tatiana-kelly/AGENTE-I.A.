import { timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { z } from "zod";
import { orchestrate } from "../orchestrator/index.js";
import { loadExecutionModeFromEnv, type SecurityContext } from "../orchestrator/securityLayer.js";
import type { OrchestrationRepository } from "../persistence/index.js";
import type { ProviderManager } from "../orchestrator/providerManager.js";

const orchestrateBodySchema = z.object({
  task: z.string().trim().min(1).max(100_000),
  project: z.string().trim().min(1).max(200).regex(/^[a-zA-Z0-9_-]+$/).optional(),
  reusePolicy: z.enum(["allow", "refresh"]).optional(),
}).strict();

const continueBodySchema = z.object({
  approved: z.literal(true),
  approvedMaxCostUsd: z.number().finite().nonnegative(),
}).strict();

export interface ApiDependencies {
  repository: OrchestrationRepository;
  providerManager: ProviderManager;
  webhookSecret: string;
  security?: SecurityContext;
  maxBodyBytes?: number;
}

export function createApiHandler(dependencies: ApiDependencies) {
  const webhookSecret = dependencies.webhookSecret.trim();
  if (webhookSecret.length < 32) throw new Error("N8N_WEBHOOK_SECRET deve ter ao menos 32 caracteres.");
  const security = dependencies.security ?? loadExecutionModeFromEnv();
  const maxBodyBytes = dependencies.maxBodyBytes ?? 128 * 1024;

  return async (request: IncomingMessage, response: ServerResponse): Promise<void> => {
    try {
      if (!authorized(request.headers.authorization, webhookSecret)) {
        throw new ApiError(401, "Não autorizado.");
      }

      const url = new URL(request.url ?? "/", "http://orchestrator.local");
      if (request.method === "POST" && url.pathname === "/orchestrate") {
        const body = orchestrateBodySchema.parse(await readJsonBody(request, maxBodyBytes));
        const result = await orchestrate(body, {
          repository: dependencies.repository,
          providerManager: dependencies.providerManager,
          security,
        });
        writeJson(response, 200, result);
        return;
      }

      const taskMatch = url.pathname.match(/^\/tasks\/([0-9a-f-]{36})$/i);
      if (request.method === "GET" && taskMatch?.[1]) {
        const snapshot = await dependencies.repository.getTask(taskMatch[1]);
        if (!snapshot) throw new ApiError(404, "Tarefa não encontrada.");
        writeJson(response, 200, snapshot);
        return;
      }

      const continueMatch = url.pathname.match(/^\/tasks\/([0-9a-f-]{36})\/continue$/i);
      if (request.method === "POST" && continueMatch?.[1]) {
        const approval = continueBodySchema.parse(await readJsonBody(request, maxBodyBytes));
        const originalTaskId = continueMatch[1];
        const snapshot = await dependencies.repository.getTask(originalTaskId);
        if (!snapshot) throw new ApiError(404, "Tarefa não encontrada.");
        if (snapshot.task.status !== "awaiting_approval") {
          throw new ApiError(409, "Tarefa não está aguardando aprovação.");
        }

        const approvedAt = new Date().toISOString();
        const claimed = await dependencies.repository.claimTaskForContinuation(originalTaskId, approvedAt);
        if (!claimed) throw new ApiError(409, "Tarefa já foi continuada ou mudou de estado.");

        try {
          const result = await orchestrate(snapshot.task.request, {
            repository: dependencies.repository,
            providerManager: dependencies.providerManager,
            security: { mode: "ASSISTED", dryRun: false, approvalGranted: true },
            continuedFromTaskId: originalTaskId,
            approval: { approved: true, source: "n8n", approvedAt, approvedMaxCostUsd: approval.approvedMaxCostUsd },
            approvedMaxCostUsd: approval.approvedMaxCostUsd,
          });
          await dependencies.repository.updateTask(originalTaskId, {
            status: "completed",
            requiresApproval: false,
            updatedAt: new Date().toISOString(),
          });
          writeJson(response, 200, result);
          return;
        } catch (error) {
          await dependencies.repository.updateTask(originalTaskId, {
            status: "failed",
            requiresApproval: false,
            updatedAt: new Date().toISOString(),
          });
          throw error;
        }
      }

      throw new ApiError(404, "Endpoint não encontrado.");
    } catch (error) {
      if (error instanceof ApiError) {
        writeJson(response, error.statusCode, { error: error.message });
        return;
      }
      if (error instanceof z.ZodError) {
        writeJson(response, 400, { error: "Payload inválido.", issues: error.issues.map(({ path, message }) => ({ path, message })) });
        return;
      }
      writeJson(response, 500, { error: "Falha interna do Orchestrator." });
    }
  };
}

class ApiError extends Error {
  constructor(
    readonly statusCode: number,
    message: string,
  ) {
    super(message);
  }
}

function authorized(authorization: string | undefined, expectedSecret: string): boolean {
  if (!authorization?.startsWith("Bearer ")) return false;
  const received = Buffer.from(authorization.slice("Bearer ".length), "utf8");
  const expected = Buffer.from(expectedSecret, "utf8");
  return received.length === expected.length && timingSafeEqual(received, expected);
}

async function readJsonBody(request: IncomingMessage, maxBodyBytes: number): Promise<unknown> {
  if (!request.headers["content-type"]?.toLowerCase().startsWith("application/json")) {
    throw new ApiError(415, "Content-Type deve ser application/json.");
  }
  const declaredLength = Number(request.headers["content-length"] ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > maxBodyBytes) {
    throw new ApiError(413, "Payload excede o limite permitido.");
  }

  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += buffer.length;
    if (bytes > maxBodyBytes) throw new ApiError(413, "Payload excede o limite permitido.");
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ApiError(400, "JSON inválido.");
  }
}

function writeJson(response: ServerResponse, statusCode: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(payload);
}
