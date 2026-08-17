import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { InMemoryOrchestrationRepository } from "../src/persistence/index.js";
import {
  initializeProjectKit,
  loadManifestContext,
  loadProjectManifest,
  parseProjectManifest,
  syncProjectFromRoot,
} from "../src/projects/index.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

describe("AI-PROJECT.yaml", () => {
  it("carrega o manifesto e produz snapshot verificável do contexto", async () => {
    const root = await createProjectFixture();
    const manifest = await loadProjectManifest(root);
    const context = await loadManifestContext(root, manifest);

    expect(manifest).toMatchObject({ project_id: "demo-project", access: { default: "read_only" } });
    expect(context.files["PROJECT-CONTEXT.md"]).toContain("Projeto demo");
    expect(context.missing).toEqual(["ARCHITECTURE.md"]);
    expect(context.sha256).toMatch(/^[a-f0-9]{64}$/);
  });

  it("rejeita caminhos absolutos, Windows e traversal", () => {
    for (const unsafePath of ["../secrets", "/etc/passwd", "C:/Users/secret", "folder\\secret"]) {
      expect(() => parseProjectManifest(manifestYaml(unsafePath))).toThrow();
    }
  });

  it("sincroniza projeto e permissões no registro", async () => {
    const root = await createProjectFixture();
    const repository = new InMemoryOrchestrationRepository();
    const project = await syncProjectFromRoot(repository, root);
    await repository.upsertProjectPermission({
      projectId: project.id,
      principalType: "agent",
      principalId: "codex",
      capability: "read_context",
      createdAt: new Date().toISOString(),
    });

    expect(await repository.listProjects()).toHaveLength(1);
    expect(await repository.getProject("demo-project")).toMatchObject({
      repository: "sal/demo-project",
      contextFiles: { "PROJECT-CONTEXT.md": expect.stringContaining("Projeto demo") },
    });
    expect(await repository.listProjectPermissions("demo-project")).toMatchObject([
      { principalId: "codex", capability: "read_context" },
    ]);
  });

  it("instala o kit sem sobrescrever arquivos existentes", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "sal-ai-onboarding-"));
    temporaryDirectories.push(root);
    await writeFile(path.join(root, "AGENTS.md"), "# Regra existente\n", "utf8");

    const first = await initializeProjectKit({
      projectRoot: root,
      projectId: "new-project",
      name: "Novo Projeto",
      repository: "sal/new-project",
    });
    const second = await initializeProjectKit({
      projectRoot: root,
      projectId: "new-project",
      name: "Novo Projeto",
      repository: "sal/new-project",
    });

    expect(first.existing).toContain("AGENTS.md");
    expect(first.created).toContain("AI-PROJECT.yaml");
    expect(second.created).toEqual([]);
    expect(second.existing).toHaveLength(first.created.length + first.existing.length);
    expect((await loadProjectManifest(root)).project_id).toBe("new-project");
  });
});

async function createProjectFixture(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "sal-ai-project-"));
  temporaryDirectories.push(root);
  await mkdir(path.join(root, ".ai"));
  await writeFile(path.join(root, "AI-PROJECT.yaml"), manifestYaml("src/**"), "utf8");
  await writeFile(path.join(root, ".ai", "PROJECT-CONTEXT.md"), "# Projeto demo\n", "utf8");
  return root;
}

function manifestYaml(allowedPath: string): string {
  return `
version: 1
project_id: demo-project
name: Projeto Demo
repository: sal/demo-project
default_branch: main
context:
  root: .ai
  files:
    - PROJECT-CONTEXT.md
    - ARCHITECTURE.md
access:
  default: read_only
  allowed_paths:
    - "${allowedPath}"
  denied_paths: []
commands:
  test: npm test
changes:
  require_branch: true
  require_tests: true
  require_human_approval_for:
    - push
`;
}
