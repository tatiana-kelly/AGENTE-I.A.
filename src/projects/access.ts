import type {
  OrchestrationRepository,
  ProjectCapability,
  ProjectPrincipalType,
  ProjectRecord,
} from "../persistence/index.js";

export interface ProjectPrincipal {
  type: ProjectPrincipalType;
  id: string;
}

export async function canAccessProject(
  repository: OrchestrationRepository,
  projectId: string,
  principal: ProjectPrincipal,
  capability: ProjectCapability,
): Promise<boolean> {
  const permissions = await repository.listProjectPermissions(projectId);
  return permissions.some(
    (permission) =>
      permission.principalType === principal.type &&
      permission.principalId === principal.id &&
      (permission.capability === capability || permission.capability === "admin"),
  );
}

export async function listAccessibleProjects(
  repository: OrchestrationRepository,
  principal: ProjectPrincipal,
  capability: ProjectCapability = "read_context",
): Promise<ProjectRecord[]> {
  const projects = await repository.listProjects();
  const access = await Promise.all(
    projects.map(async (project) => ({ project, allowed: await canAccessProject(repository, project.id, principal, capability) })),
  );
  return access.filter(({ allowed }) => allowed).map(({ project }) => project);
}
