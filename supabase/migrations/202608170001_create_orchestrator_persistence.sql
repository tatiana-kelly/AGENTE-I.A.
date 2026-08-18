-- FASE 11: schema exclusivo do AI Orchestrator.
-- O acesso direto de anon/authenticated permanece bloqueado; o backend usa service_role.

create table if not exists public.ai_tasks (
  id uuid primary key,
  task_text text not null check (length(task_text) between 1 and 100000),
  project text,
  status text not null check (status in ('received', 'running', 'completed', 'awaiting_approval', 'blocked', 'failed')),
  classification jsonb not null,
  routing jsonb not null,
  plan jsonb not null,
  execution_mode text not null check (execution_mode in ('READ_ONLY', 'ASSISTED', 'AUTONOMOUS')),
  dry_run boolean not null,
  requires_approval boolean not null default false,
  validation jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_runs (
  id uuid primary key,
  task_id uuid not null references public.ai_tasks(id) on delete cascade,
  step_index integer not null check (step_index >= 0),
  provider text not null check (provider in ('openai', 'manus', 'anthropic', 'gemini')),
  fallback_for text check (fallback_for is null or fallback_for in ('openai', 'manus', 'anthropic', 'gemini')),
  purpose text not null,
  status text not null check (status in ('running', 'success', 'error', 'skipped', 'blocked')),
  output text,
  reason text,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.ai_evidence (
  id bigint generated always as identity primary key,
  task_id uuid not null references public.ai_tasks(id) on delete cascade,
  run_id uuid references public.ai_runs(id) on delete set null,
  project text,
  provider text not null check (provider in ('openai', 'manus', 'anthropic', 'gemini')),
  model text,
  skill text,
  routing_reason text not null,
  sources jsonb not null default '[]'::jsonb check (jsonb_typeof(sources) = 'array'),
  evidence jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence) = 'array'),
  result text not null default '',
  status text not null check (status in ('success', 'error', 'skipped', 'blocked')),
  reason text,
  confidence double precision not null check (confidence between 0 and 1),
  recorded_at timestamptz not null default now(),
  limitations text,
  fallback_triggered boolean not null default false,
  fallback_reason text
);

create index if not exists ai_tasks_status_updated_idx on public.ai_tasks(status, updated_at desc);
create index if not exists ai_runs_task_step_idx on public.ai_runs(task_id, step_index, started_at);
create index if not exists ai_evidence_task_recorded_idx on public.ai_evidence(task_id, recorded_at);

alter table public.ai_tasks enable row level security;
alter table public.ai_runs enable row level security;
alter table public.ai_evidence enable row level security;

revoke all on public.ai_tasks from anon, authenticated;
revoke all on public.ai_runs from anon, authenticated;
revoke all on public.ai_evidence from anon, authenticated;
revoke all on sequence public.ai_evidence_id_seq from anon, authenticated;

grant all on public.ai_tasks to service_role;
grant all on public.ai_runs to service_role;
grant all on public.ai_evidence to service_role;
grant usage, select on sequence public.ai_evidence_id_seq to service_role;
