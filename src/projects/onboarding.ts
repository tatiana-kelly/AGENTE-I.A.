import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { stringify } from "yaml";
import { projectManifestSchema, type ProjectManifest } from "./manifest.js";

export interface InitializeProjectInput {
  projectRoot: string;
  projectId: string;
  name: string;
  repository: string;
  defaultBranch?: string;
}

export interface InitializeProjectResult {
  created: string[];
  existing: string[];
}

export async function initializeProjectKit(input: InitializeProjectInput): Promise<InitializeProjectResult> {
  const manifest = projectManifestSchema.parse({
    version: 1,
    project_id: input.projectId,
    name: input.name,
    repository: input.repository,
    default_branch: input.defaultBranch ?? "main",
    context: {},
    access: {
      default: "read_only",
      allowed_paths: ["src/**", "tests/**", "docs/**", ".ai/**", ".agents/**", "*.md", "*.json", "*.yaml"],
      denied_paths: [".env", "**/.env", "**/credentials/**", "**/service_account.json", "**/*.pem", "**/*.key"],
    },
    commands: {},
    changes: {},
  });

  const files = projectTemplates(manifest);
  const result: InitializeProjectResult = { created: [], existing: [] };
  await mkdir(input.projectRoot, { recursive: true });

  for (const [relativePath, contents] of Object.entries(files)) {
    const destination = path.resolve(input.projectRoot, relativePath);
    assertInside(input.projectRoot, destination);
    await mkdir(path.dirname(destination), { recursive: true });
    try {
      await writeFile(destination, contents, { encoding: "utf8", flag: "wx" });
      result.created.push(relativePath);
    } catch (error) {
      if (isAlreadyExists(error)) {
        result.existing.push(relativePath);
        continue;
      }
      throw error;
    }
  }
  return result;
}

function projectTemplates(manifest: ProjectManifest): Record<string, string> {
  return {
    "AI-PROJECT.yaml": stringify(manifest, { lineWidth: 120 }),
    "AGENTS.md": `# Instruções para agentes

Leia \`AI-PROJECT.yaml\` e os arquivos autorizados em \`.ai/\` antes de agir. Comece em leitura, respeite \`allowed_paths\`/\`denied_paths\` e execute somente comandos declarados no manifesto.

Não faça push, pull request, deploy ou migration sem a aprovação exigida. Preserve a divisão oficial de papéis do SAL AI OS; mudanças estruturais exigem aprovação da Tatiana.
`,
    "CLAUDE.md": `@AGENTS.md

## Claude Code

Claude Code é o construtor oficial. Trabalhe em branch, rode os comandos de validação declarados e não publique alterações sem aprovação.
`,
    ".ai/PROJECT-CONTEXT.md": `# Contexto do projeto

Projeto: ${manifest.name}\n\nPreencher objetivo, proprietários, usuários e limites reais. Não inventar informações ausentes.
`,
    ".ai/ARCHITECTURE.md": "# Arquitetura\n\nPreencher componentes, integrações, fluxos e decisões arquiteturais vigentes.\n",
    ".ai/BUSINESS-RULES.md": "# Regras de negócio\n\nPreencher regras confirmadas, exceções e aprovações necessárias.\n",
    ".ai/DATA-DICTIONARY.md": "# Dicionário de dados\n\nPreencher entidades, campos, fontes e classificação de sensibilidade.\n",
    ".ai/AI-INSTRUCTIONS.md": "# Instruções para IA\n\nCitar evidências concretas, declarar limitações e nunca ultrapassar os caminhos autorizados.\n",
    ".agents/skills/sal-project/SKILL.md": SAL_PROJECT_SKILL,
    ".agents/skills/sal-project/agents/openai.yaml": `interface:
  display_name: "SAL Project"
  short_description: "Audita e melhora projetos com o SAL AI"
  default_prompt: "Use $sal-project para auditar este projeto com o AI Orchestrator."
`,
  };
}

const SAL_PROJECT_SKILL = `---
name: sal-project
description: Auditar, compreender e melhorar um projeto integrado ao SAL AI Orchestrator. Usar para auditoria, melhoria contínua, contexto, AI-PROJECT.yaml ou conformidade das instruções de agentes.
---

# SAL Project

1. Ler \`AI-PROJECT.yaml\`, \`AGENTS.md\` e o contexto autorizado.
2. Restringir leituras a \`allowed_paths\` e nunca acessar \`denied_paths\`.
3. Começar em leitura e sustentar achados em evidãncias.
4. Exigir as aprovações declaradas antes de escrever, publicar, migrar ou implantar.
5. Executar somente comandos declarados no manifesto.
6. Preservar os papéis oficiais do SAL AI OS.
`;

function assertInside(root: string, candidate: string): void {
  const relative = path.relative(path.resolve(root), candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Destino fora do projeto.");
}

function isAlreadyExists(error: unknown): boolean {
  return error instanceof Error && "code" in error && (error as NodeJS.ErrnoException).code === "EEXIST";
}
