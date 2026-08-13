import { readFile } from "node:fs/promises";
import path from "node:path";

/** FASE 5 canonical per-project context files. Only these are ever loaded. */
const CONTEXT_FILES = [
  "PROJECT-CONTEXT.md",
  "DATA-DICTIONARY.md",
  "BUSINESS-RULES.md",
  "ARCHITECTURE.md",
  "AI-INSTRUCTIONS.md",
] as const;

const SAFE_PROJECT_NAME = /^[a-zA-Z0-9_-]+$/;

export interface ResolvedContext {
  project: string | null;
  loaded: Record<string, string>;
  missing: string[];
}

/**
 * Loads only the named project's context files from `projects/<project>/`.
 * Never reads the wider repository. Rejects project names outside
 * `[a-zA-Z0-9_-]` to prevent path traversal via the /orchestrate API input.
 */
export async function resolveContext(
  project: string | undefined,
  projectsRoot: string = path.join(process.cwd(), "projects"),
): Promise<ResolvedContext> {
  if (!project) {
    return { project: null, loaded: {}, missing: [] };
  }

  if (!SAFE_PROJECT_NAME.test(project)) {
    throw new Error(`Nome de projeto inválido: "${project}". Use apenas letras, números, "-" e "_".`);
  }

  const projectDir = path.join(projectsRoot, project);
  const loaded: Record<string, string> = {};
  const missing: string[] = [];

  for (const fileName of CONTEXT_FILES) {
    try {
      loaded[fileName] = await readFile(path.join(projectDir, fileName), "utf-8");
    } catch {
      missing.push(fileName);
    }
  }

  return { project, loaded, missing };
}
