-- Registro exclusivo de projetos acessíveis pelo AI Orchestrator.

create table if not exists public.ai_projects (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'),
  name text not null check (length(name) between 1 and 120),
  repository text not null unique,
  default_branch text not null default 'main',
  manifest jsonb not null,
  context_files jsonb not null default '{}'::jsonb check (jsonb_typeof(context_files) = 'object'),
  missing_context_files jsonb not null default '[]'::jsonb check (jsonb_typeof(missing_context_files) = 'array'),
  context_sha256 text not null check (context_sha256 ~ '^[a-f0-9]{64}$'),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_project_permissions (
  project_id text not null references public.ai_projects(id) on delete cascade,
  principal_type text not null check (principal_type in ('user', 'service', 'agent')),
  principal_id text not null check (length(principal_id) between 1 and 200),
  capability text not null check (capability in ('read_context', 'audit', 'execute_assisted', 'approve', 'admin')),
  created_at timestamptz not null default now(),
  primary key (project_id, principal_type, principal_id, capability)
);

create index if not exists ai_projects_active_idx on public.ai_projects(active, id);
create index if not exists ai_project_permissions_principal_idx
  on public.ai_project_permissions(principal_type, principal_id, project_id);

alter table public.ai_projects enable row level security;
alter table public.ai_project_permissions enable row level security;

revoke all on public.ai_projects from anon, authenticated;
revoke all on public.ai_project_permissions from anon, authenticated;
grant all on public.ai_projects to service_role;
grant all on public.ai_project_permissions to service_role;
