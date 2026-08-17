import path from "node:path";
import {
  buildSupabaseRepositoryFromEnv,
  type ProjectCapability,
  type ProjectPrincipalType,
} from "../persistence/index.js";
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
} else if (command === "grant") {
  const repository = buildSupabaseRepositoryFromEnv();
  if (!repository) throw new Error("Grant exige SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.");
  if (!rootArgument) throw new Error("Grant exige o project_id como segundo argumento.");
  const values = parseFlags(argumentsList);
  const permission = {
    projectId: rootArgument,
    principalType: parsePrincipalType(required(values, "type")),
    principalId: required(values, "principal"),
    capability: parseCapability(required(values, "capability")),
    createdAt: new Date().toISOString(),
  };
  if (!(await repository.getProject(permission.projectId))) throw new Error(`Projeto ${permission.projectId} não registrado.`);
  await repository.upsertProjectPermission(permission);
  console.log(JSON.stringify({ granted: true, ...permission }, null, 2));
} else {
  throw new Error("Uso: project <init|validate|sync|grant> <diretório|project_id> [opções]");
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

function parsePrincipalType(value: string): ProjectPrincipalType {
  if (value === "user" || value === "service" || value === "agent") return value;
  throw new Error("--type deve ser user, service ou agent.");
}

function parseCapability(value: string): ProjectCapability {
  if (value === "read_context" || value === "audit" || value === "execute_assisted" || value === "approve" || value === "admin") {
    return value;
  }
  throw new Error("--capability inválida.");
}
