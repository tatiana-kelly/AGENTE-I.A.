import type { OrchestrationRepository, ProjectRecord } from "../persistence/index.js";
import { loadManifestContext, loadProjectManifest } from "./manifest.js";

export async function syncProjectFromRoot(
  repository: OrchestrationRepository,
  projectRoot: string,
): Promise<ProjectRecord> {
  const manifest = await loadProjectManifest(projectRoot);
  const context = await loadManifestContext(projectRoot, manifest);
  const now = new Date().toISOString();
  const project: ProjectRecord = {
    id: manifest.project_id,
    name: manifest.name,
    repository: manifest.repository,
    defaultBranch: manifest.default_branch,
    manifest,
    contextFiles: context.files,
    missingContextFiles: context.missing,
    contextSha256: context.sha256,
    active: true,
    updatedAt: now,
  };
  await repository.upsertProject(project);
  return project;
}
