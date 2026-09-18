-- sal.agent-run/1.0 — persistência mínima do /v1/agent-runs (idempotência + auditoria técnica).
-- STATUS: APLICADA em 2026-09-17 no projeto sal-ai-orchestrator (zkwfupxztxczeadrlsri), com autorização da Tatiana.
-- Não guarda memória empresarial: caso, decisão, ação, verificação e aprendizado ficam no SAL Intelligence OS.

create table if not exists public.ai_agent_runs (
    idempotency_key_hash text primary key,
    request_hash         text not null,
    response             jsonb not null,
    created_at           timestamptz not null default now(),
    expires_at           timestamptz not null
);

create index if not exists ai_agent_runs_expires_at_idx on public.ai_agent_runs (expires_at);

create table if not exists public.ai_agent_run_audit (
    id                    bigint generated always as identity primary key,
    request_id            text not null,
    idempotency_key_hash  text not null,
    principal             text not null,
    project               text not null,
    agent                 text not null,
    agent_version         text not null,
    provider              text not null,
    model                 text not null,
    attempt               integer not null,
    status                text not null,
    latency_ms            text not null,
    input_tokens          text not null,
    output_tokens         text not null,
    cost_usd              text not null,
    fallback_triggered    boolean not null,
    review_status         text not null,
    validation_status     text not null,
    created_at            timestamptz not null default now()
);

create index if not exists ai_agent_run_audit_request_idx on public.ai_agent_run_audit (request_id);
create index if not exists ai_agent_run_audit_created_idx on public.ai_agent_run_audit (created_at desc);

-- Métricas ausentes são gravadas como o texto 'unknown' — nunca como 0.
alter table public.ai_agent_runs      enable row level security;
alter table public.ai_agent_run_audit enable row level security;

revoke all on public.ai_agent_runs      from anon, authenticated;
revoke all on public.ai_agent_run_audit from anon, authenticated;
