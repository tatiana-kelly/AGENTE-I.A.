-- One-time OAuth authorization-code claims for the remote MCP connector.

create table if not exists public.ai_oauth_grants (
  grant_id text primary key check (grant_id ~ '^[a-f0-9]{64}$'),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  created_at timestamptz not null default now(),
  check (consumed_at is null or consumed_at >= created_at)
);

create index if not exists ai_oauth_grants_expiry_idx
  on public.ai_oauth_grants(expires_at)
  where consumed_at is null;

alter table public.ai_oauth_grants enable row level security;
revoke all on public.ai_oauth_grants from anon, authenticated;
grant all on public.ai_oauth_grants to service_role;
