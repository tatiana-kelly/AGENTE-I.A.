#!/usr/bin/env node
// Espelha o contexto autorizado de um projeto integrado para dentro deste repo.
//
// O dono do contexto é o PROJETO (pasta `.ai/` no repositório dele). O Orchestrator
// roda na Vercel e não enxerga o filesystem do projeto, então `projects/<id>/` precisa
// ser uma cópia. Este script existe para que essa cópia nunca seja feita à mão — foi
// assim que `projects/torre-controle/` ficou apontando para um caminho local morto.
//
// Uso:
//   node scripts/sync-project-context.mjs <project_id> <caminho-do-projeto>
//   node scripts/sync-project-context.mjs --check <project_id> <caminho-do-projeto>
//
// `--check` não escreve nada: sai com código 1 se o espelho estiver defasado. Serve
// para CI e para conferir antes de commitar.

import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

const CONTEXT_FILES = [
  "PROJECT-CONTEXT.md",
  "DATA-DICTIONARY.md",
  "BUSINESS-RULES.md",
  "ARCHITECTURE.md",
  "AI-INSTRUCTIONS.md",
];

const SAFE_PROJECT_NAME = /^[a-zA-Z0-9_-]+$/;

const argv = process.argv.slice(2);
const checkOnly = argv[0] === "--check";
const [projectId, projectRoot] = checkOnly ? argv.slice(1) : argv;

if (!projectId || !projectRoot) {
  console.error("Uso: node scripts/sync-project-context.mjs [--check] <project_id> <caminho-do-projeto>");
  process.exit(2);
}

// Mesma validação do contextResolver: o id vira nome de pasta.
if (!SAFE_PROJECT_NAME.test(projectId)) {
  console.error(`Nome de projeto inválido: "${projectId}". Use apenas letras, números, "-" e "_".`);
  process.exit(2);
}

const sourceDir = path.resolve(projectRoot, ".ai");
const targetDir = path.resolve(process.cwd(), "projects", projectId);

await mkdir(targetDir, { recursive: true });

const stale = [];
const missing = [];
let written = 0;

for (const fileName of CONTEXT_FILES) {
  let source;
  try {
    source = await readFile(path.join(sourceDir, fileName), "utf8");
  } catch {
    missing.push(fileName);
    continue;
  }

  const targetPath = path.join(targetDir, fileName);
  let current = null;
  try {
    current = await readFile(targetPath, "utf8");
  } catch {
    // espelho ainda não existe
  }

  if (current === source) continue;

  stale.push(fileName);
  if (!checkOnly) {
    await writeFile(targetPath, source, "utf8");
    written += 1;
  }
}

if (missing.length > 0) {
  console.warn(`Ausentes em ${sourceDir}: ${missing.join(", ")} (não é erro — o Context Resolver reporta em missing[]).`);
}

if (checkOnly) {
  if (stale.length > 0) {
    console.error(`Espelho defasado em projects/${projectId}/: ${stale.join(", ")}`);
    console.error(`Rode: node scripts/sync-project-context.mjs ${projectId} "${projectRoot}"`);
    process.exit(1);
  }
  console.log(`projects/${projectId}/ está em dia com ${sourceDir}`);
  process.exit(0);
}

console.log(
  written > 0
    ? `Sincronizados ${written} arquivo(s) de ${sourceDir} para projects/${projectId}/: ${stale.join(", ")}`
    : `projects/${projectId}/ já estava em dia com ${sourceDir}`,
);
