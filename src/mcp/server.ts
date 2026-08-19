import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import type { OrchestrationRepository } from "../persistence/index.js";
import { canAccessProject, listAccessibleProjects, type ProjectPrincipal } from "../projects/index.js";
import type { OrchestrationResult } from "../orchestrator/types.js";

export interface ProjectMcpDependencies {
  repository: OrchestrationRepository;
  principal: ProjectPrincipal;
  runTask?: (input: { task: string; project: string; reusePolicy?: "allow" | "refresh" }) => Promise<OrchestrationResult>;
}

export function createProjectMcpServer(dependencies: ProjectMcpDependencies): McpServer {
  const server = new McpServer({ name: "sal-ai-orchestrator", version: "0.1.0" });

  server.registerTool(
    "projects_list",
    {
      title: "Listar projetos SAL AI",
      description: "Lista somente projetos para os quais o principal atual possui read_context.",
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async () => {
      const projects = await listAccessibleProjects(dependencies.repository, dependencies.principal);
      const output = projects.map((project) => ({
        projectId: project.id,
        name: project.name,
        repository: project.repository,
        defaultBranch: project.defaultBranch,
        contextSha256: project.contextSha256,
        updatedAt: project.updatedAt,
      }));
      return asJsonResult(output);
    },
  );

  server.registerTool(
    "projects_get_context",
    {
      title: "Obter contexto autorizado",
      description: "Retorna manifesto e snapshot de contexto de um projeto autorizado, sem acessar o filesystem do cliente.",
      inputSchema: { projectId: z.string().min(3).max(64) },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ projectId }) => {
      if (!(await canAccessProject(dependencies.repository, projectId, dependencies.principal, "read_context"))) {
        return toolError("Projeto inexistente ou acesso negado.");
      }
      const project = await dependencies.repository.getProject(projectId);
      if (!project?.active) return toolError("Projeto inexistente ou acesso negado.");
      return asJsonResult({
        projectId: project.id,
        manifest: project.manifest,
        contextFiles: project.contextFiles,
        missingContextFiles: project.missingContextFiles,
        contextSha256: project.contextSha256,
        updatedAt: project.updatedAt,
      });
    },
  );

  server.registerTool(
    "tasks_get",
    {
      title: "Consultar tarefa do Orchestrator",
      description: "Consulta tarefa, runs e evidências quando ela pertence a um projeto autorizado.",
      inputSchema: { taskId: z.string().uuid() },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    },
    async ({ taskId }) => {
      const snapshot = await dependencies.repository.getTask(taskId);
      const projectId = snapshot?.task.request.project;
      if (!snapshot || !projectId) return toolError("Tarefa inexistente ou sem projeto autorizado.");
      if (!(await canAccessProject(dependencies.repository, projectId, dependencies.principal, "read_context"))) {
        return toolError("Tarefa inexistente ou acesso negado.");
      }
      return asJsonResult(snapshot);
    },
  );

  if (dependencies.runTask) {
    server.registerTool(
      "tasks_run_audit",
      {
        title: "Executar auditoria autorizada",
        description: "Executa o Orchestrator em um projeto autorizado. O gate de segurança, custo, evidência e aprovação humana continua obrigatório.",
        inputSchema: {
          task: z.string().trim().min(1).max(100_000),
          projectId: z.string().min(3).max(64),
          reusePolicy: z.enum(["allow", "refresh"]).optional(),
        },
      },
      async ({ task, projectId, reusePolicy }) => {
        if (!(await canAccessProject(dependencies.repository, projectId, dependencies.principal, "audit"))) {
          return toolError("Projeto inexistente ou acesso de auditoria negado.");
        }
        return asJsonResult(await dependencies.runTask!({ task, project: projectId, reusePolicy }));
      },
    );
  }

  return server;
}

function asJsonResult(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function toolError(message: string) {
  return { isError: true, content: [{ type: "text" as const, text: message }] };
}
