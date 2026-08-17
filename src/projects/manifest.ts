import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { parse } from "yaml";
import { z } from "zod";

const relativePathSchema = z.string().min(1).max(300).refine(isSafeRelativePath, {
  message: "O caminho deve ser relativo, usar '/' e não pode escapar do projeto.",
});

export const projectManifestSchema = z.object({
  version: z.literal(1),
  project_id: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/),
  name: z.string().trim().min(1).max(120),
  repository: z.string().regex(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/),
  default_branch: z.string().regex(/^[A-Za-z0-9._/-]+$/).default("main"),
  context: z.object({
    root: relativePathSchema.default(".ai"),
    files: z.array(relativePathSchema).min(1).max(20).default([
      "PROJECT-CONTEXT.md",
      "ARCHITECTURE.md",
      "BUSINESS-RULES.md",
      "DATA-DICTIONARY.md",
      "AI-INSTRUCTIONS.md",
    ]),
  }),
  access: z.object({
    default: z.enum(["read_only", "assisted"]).default("read_only"),
    allowed_paths: z.array(relativePathSchema).min(1).max(100),
    denied_paths: z.array(relativePathSchema).max(100).default([]),
  }),
  commands: z.record(z.string().regex(/^[a-z][a-z0-9_-]*$/), z.string().trim().min(1).max(500)).default({}),
  changes: z.object({
    require_branch: z.boolean().default(true),
    require_tests: z.boolean().default(true),
    require_human_approval_for: z.array(z.enum(["push", "pull_request", "deploy", "database_migration"])).default([
      "push",
      "pull_request",
      "deploy",
      "database_migration",
    ]),
  }),
}).strict();

export type ProjectManifest = z.infer<typeof projectManifestSchema>;

export interface LoadedProjectContext {
  files: Record<string, string>;
  missing: string[];
  sha256: string;
}

export async function loadProjectManifest(projectRoot: string): Promise<ProjectManifest> {
  const contents = await readFile(path.join(projectRoot, "AI-PROJECT.yaml"), "utf8");
  return parseProjectManifest(contents);
}

export function parseProjectManifest(contents: string): ProjectManifest {
  let parsed: unknown;
  try {
    parsed = parse(contents);
  } catch (error) {
    throw new Error(`AI-PROJECT.yaml inválido: ${error instanceof Error ? error.message : String(error)}`);
  }
  return projectManifestSchema.parse(parsed);
}

export async function loadManifestContext(
  projectRoot: string,
  manifest: ProjectManifest,
  maxTotalBytes = 500_000,
): Promise<LoadedProjectContext> {
  const realProjectRoot = await realpath(projectRoot);
  const contextRoot = await realpath(path.resolve(realProjectRoot, manifest.context.root));
  assertInsideProject(realProjectRoot, contextRoot);
  const files: Record<string, string> = {};
  const missing: string[] = [];
  let totalBytes = 0;

  for (const fileName of manifest.context.files) {
    try {
      const filePath = await realpath(path.resolve(contextRoot, fileName));
      assertInsideProject(contextRoot, filePath);
      const contents = await readFile(filePath, "utf8");
      totalBytes += Buffer.byteLength(contents);
      if (totalBytes > maxTotalBytes) throw new Error(`Contexto excede ${maxTotalBytes} bytes.`);
      files[fileName] = contents;
    } catch (error) {
      if (
        error instanceof Error &&
        (error.message.startsWith("Contexto excede") || error.message === "Caminho de contexto fora do projeto.")
      ) throw error;
      missing.push(fileName);
    }
  }

  const canonical = Object.entries(files)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, contents]) => `${name}\0${contents}`)
    .join("\0");
  return { files, missing, sha256: createHash("sha256").update(canonical).digest("hex") };
}

function isSafeRelativePath(value: string): boolean {
  if (!value || value.includes("\0") || value.includes("\\") || path.posix.isAbsolute(value) || /^[A-Za-z]:/.test(value)) return false;
  return !value.split("/").some((segment) => segment === "..");
}

function assertInsideProject(root: string, candidate: string): void {
  const relative = path.relative(path.resolve(root), candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Caminho de contexto fora do projeto.");
}
