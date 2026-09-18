-- Adiciona a capability 'agent_run' ao registro de permissões do Orchestrator.
-- STATUS: APLICADA em 2026-09-17 no projeto sal-ai-orchestrator (zkwfupxztxczeadrlsri), com autorização da Tatiana.
--
-- Mudança aditiva: nenhuma permissão existente muda de significado e nenhuma linha é alterada.
-- Sem ela, conceder agent_run é recusado pelo CHECK atual — ou seja, o banco já é fail-closed.

alter table public.ai_project_permissions
  drop constraint if exists ai_project_permissions_capability_check;

alter table public.ai_project_permissions
  add constraint ai_project_permissions_capability_check
  check (capability in ('read_context', 'audit', 'execute_assisted', 'approve', 'agent_run', 'admin'));
