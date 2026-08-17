import path from "node:path";
import { buildSupabaseRepositoryFromEnv } from "../persistence/index.js";
import { initializeProjectKit, loadProjectManifest, syncProjectFromRoot } from "../projects/index.js";

const [command, rootArgument, ...argumentsList] = process.argv.slice(2);
const projectRoot = path.resolve(rootArgument ?? process.cwd());

if (command === "init") {
  const values = parseFlags(argumentsList);
  const result = await initializeProjectKit({
    projectRoot,
    projectId: required(values, "id"),
    name: required(values, "name"),
    repository: required(values, "repository"),
    defaultBranch: values.branch,
  });
  console.log(JSON.stringify(result, null, 2));
} else if (command === "validate") {
  const manifest = await loadProjectManifest(projectRoot);
  console.log(JSON.stringify({ valid: true, projectId: manifest.project_id }, null, 2));
} else if (command === "sync") {
  const repository = buildSupabaseRepositoryFromEnv();
  if (!repository) throw new Error("Sync exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");
  const project = await syncProjectFromRoot(repository, projectRoot);
  console.log(JSON.stringify({ synced: true, projectId: project.id, contextSha256: project.contextSha256 }, null, 2));
} else {
  throw new Error("Uso: project <init|validate|sync> <diretório> [--id ... --name ... --repository ... --branch main]");
}

function parseFlags(args: string[]): Record<string, string> {
  const values: Record<string, string> = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];
    if (!flag?.startsWith("--") || !value) throw new Error(`Argumento inválido: ${flag ?? "ausente"}.`);
    values[flag.slice(2)] = value;
  }
  return values;
}

function required(values: Record<string, string>, key: string): string {
  const value = values[key];
  if (!value) throw new Error(`--${key} é obrigatório.`);
  return value;
}
