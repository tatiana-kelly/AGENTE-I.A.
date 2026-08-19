import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, describe, expect, it } from "vitest";
import { createProjectMcpServer } from "../src/mcp/index.js";
import { InMemoryOrchestrationRepository, type ProjectRecord } from "../src/persistence/index.js";
import { parseProjectManifest } from "../src/projects/index.js";
import type { OrchestrationResult } from "../src/orchestrator/types.js";

const closeCallbacks: Array<() => Promise<void>> = [];

afterEach(async () => {
  await Promise.all(closeCallbacks.splice(0).map((close) => close()));
});

describe("MCP somente leitura", () => {
  it("lista e devolve contexto apenas de projetos autorizados", async () => {
    const repository = new InMemoryOrchestrationRepository();
    await repository.upsertProject(projectRecord("allowed-project"));
    await repository.upsertProject(projectRecord("hidden-project"));
    await repository.upsertProjectPermission({
      projectId: "allowed-project",
      principalType: "agent",
      principalId: "codex",
      capability: "read_context",
      createdAt: new Date().toISOString(),
    });
    const client = await connectClient(repository);

    const list = await client.callTool({ name: "projects_list", arguments: {} });
    expect(toolText(list)).toContain("allowed-project");
    expect(toolText(list)).not.toContain("hidden-project");

    const context = await client.callTool({
      name: "projects_get_context",
      arguments: { projectId: "allowed-project" },
    });
    expect(context.isError).not.toBe(true);
    expect(toolText(context)).toContain("PROJECT-CONTEXT.md");
    expect(toolText(context)).toContain("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  });

  it("não revela se projeto sem permissão existe", async () => {
    const repository = new InMemoryOrchestrationRepository();
    await repository.upsertProject(projectRecord("hidden-project"));
    const client = await connectClient(repository);

    const result = await client.callTool({
      name: "projects_get_context",
      arguments: { projectId: "hidden-project" },
    });
    expect(result.isError).toBe(true);
    expect(toolText(result)).toBe("Projeto inexistente ou acesso negado.");
  });

  it("só executa auditoria quando o principal possui capability audit", async () => {
    const repository = new InMemoryOrchestrationRepository();
    await repository.upsertProject(projectRecord("allowed-project"));
    const runTask = async () => ({ taskId: "task-result" }) as unknown as OrchestrationResult;
    const deniedClient = await connectClient(repository, runTask);
    const denied = await deniedClient.callTool({
      name: "tasks_run_audit",
      arguments: { projectId: "allowed-project", task: "Audite em leitura." },
    });
    expect(denied.isError).toBe(true);

    await repository.upsertProjectPermission({
      projectId: "allowed-project",
      principalType: "agent",
      principalId: "codex",
      capability: "audit",
      createdAt: new Date().toISOString(),
    });
    const allowedClient = await connectClient(repository, runTask);
    const allowed = await allowedClient.callTool({
      name: "tasks_run_audit",
      arguments: { projectId: "allowed-project", task: "Audite em leitura." },
    });
    expect(allowed.isError).not.toBe(true);
    expect(toolText(allowed)).toContain("task-result");
  });
});

async function connectClient(
  repository: InMemoryOrchestrationRepository,
  runTask?: (input: { task: string; project: string; reusePolicy?: "allow" | "refresh" }) => Promise<OrchestrationResult>,
): Promise<Client> {
  const server = createProjectMcpServer({ repository, principal: { type: "agent", id: "codex" }, runTask });
  const client = new Client({ name: "test-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  closeCallbacks.push(async () => {
    await client.close();
    await server.close();
  });
  return client;
}

function projectRecord(id: string): ProjectRecord {
  const manifest = parseProjectManifest(`
version: 1
project_id: ${id}
name: ${id}
repository: sal/${id}
context: { root: .ai, files: [PROJECT-CONTEXT.md] }
access: { default: read_only, allowed_paths: [src/**], denied_paths: [] }
changes: {}
`);
  return {
    id,
    name: id,
    repository: `sal/${id}`,
    defaultBranch: "main",
    manifest,
    contextFiles: { "PROJECT-CONTEXT.md": `# ${id}` },
    missingContextFiles: [],
    contextSha256: "a".repeat(64),
    active: true,
    updatedAt: new Date().toISOString(),
  };
}

function toolText(result: Awaited<ReturnType<Client["callTool"]>>): string {
  const first = result.content[0];
  return first && first.type === "text" ? first.text : "";
}
