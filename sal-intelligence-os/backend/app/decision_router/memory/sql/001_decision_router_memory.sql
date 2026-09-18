-- Decision Router — memória persistente (case_routes, pattern_stats, playbooks)
-- STATUS: APLICADA em 2026-09-17 com autorização explícita da Tatiana.
-- Destino autorizado: projeto Supabase sal-ai-orchestrator (zkwfupxztxczeadrlsri), schema decision_router.
-- Não aplicar em relatorios-raw, pendency-tracker nem Command Deck. Nenhum objeto fora deste schema é tocado.
-- Acesso: RLS ligado e nenhuma policy para anon/authenticated (negado por padrão). A policy de escrita
-- do Router depende de aprovação futura; não usar service_role para contornar RLS.
-- O shadow runner permanece SHADOW_READ_ONLY: estas tabelas não recebem casos automaticamente.

create schema if not exists decision_router;

create table if not exists decision_router.case_routes (
    id                         text primary key,
    alert_id                   text not null,
    source                     text not null,
    metric_id                  text not null,
    case_type                  text not null,
    exact_fingerprint          text not null,
    pattern_key                text not null,
    lineage_key                text not null,
    status                     text not null check (status in ('ROUTED','BLOCKED_DATA','ESCALATED')),
    route                      text not null check (route in ('NO_AGENT','REUSE_DECISION','ONE_AGENT','MULTI_AGENT','INVESTIGATE_FIRST')),
    route_reason               text not null,
    observed_at                timestamptz not null,
    created_at                 timestamptz not null default now(),
    updated_at                 timestamptz not null default now(),
    period                     text not null,
    engine_source              text not null,
    entity_type                text not null,
    entity_id                  text not null,
    direction                  text not null check (direction in ('up','down','flat')),
    dominant_dimension         text,
    magnitude_band             text not null,
    rules_version              text not null,
    approval_flags             text[] not null default '{}',
    priority_score             numeric,
    priority_label             text,
    quality_passed             boolean not null,
    quality_score              integer not null check (quality_score between 0 and 100),
    source_quality             text not null,
    selected_agents            text[] not null default '{}',
    estimated_ai_calls         integer not null check (estimated_ai_calls >= 0),
    deterministic_outcome      text,
    -- referências aos fluxos humanos; o Router nunca preenche
    decision_id                text,
    decision_status            text not null default 'none'
                               check (decision_status in ('none','proposed','approved','rejected','request_more_evidence')),
    approved_at                timestamptz,
    diagnosis_confidence       numeric check (diagnosis_confidence between 0 and 100),
    diagnosis_status           text,
    hypotheses                 jsonb not null default '[]',
    recommendation             jsonb,
    action_id                  text,
    action_status              text not null default 'none'
                               check (action_status in ('none','open','in_progress','completed','cancelled')),
    verification_status        text not null default 'none'
                               check (verification_status in ('none','ok','partial','fail')),
    verification_result        text,
    recurrence                 boolean,
    learning_id                text,
    learning_predicted_impact  numeric,
    learning_actual_impact     numeric,
    reopen_count               integer not null default 0 check (reopen_count >= 0),
    escalation_count           integer not null default 0 check (escalation_count >= 0),
    evidence                   jsonb not null default '[]',
    route_payload              jsonb,
    constraint case_routes_exact_fingerprint_key unique (exact_fingerprint),
    constraint case_routes_approval_requires_decision
        check (decision_status <> 'approved' or (decision_id is not null and approved_at is not null)),
    constraint case_routes_verification_requires_action
        check (verification_status = 'none' or action_id is not null)
);

create index if not exists case_routes_pattern_key_idx on decision_router.case_routes (pattern_key);
create index if not exists case_routes_lineage_observed_idx on decision_router.case_routes (lineage_key, observed_at desc);
create index if not exists case_routes_metric_period_idx on decision_router.case_routes (metric_id, period);
create index if not exists case_routes_decision_status_idx on decision_router.case_routes (decision_status)
    where decision_status <> 'none';

create table if not exists decision_router.pattern_stats (
    pattern_key            text primary key,
    occurrences            integer not null default 0 check (occurrences >= 0),
    false_positives        integer not null default 0 check (false_positives >= 0),
    approved_decisions     integer not null default 0 check (approved_decisions >= 0),
    reuse_count            integer not null default 0 check (reuse_count >= 0),
    reuse_verified_fail    integer not null default 0 check (reuse_verified_fail >= 0),
    verified_ok            integer not null default 0 check (verified_ok >= 0),
    verified_fail          integer not null default 0 check (verified_fail >= 0),
    reopened               integer not null default 0 check (reopened >= 0),
    agent_calls            integer not null default 0 check (agent_calls >= 0),
    useful_agent_calls     integer not null default 0 check (useful_agent_calls >= 0),
    ai_routed_cases        integer not null default 0 check (ai_routed_cases >= 0),
    last_seen_at           timestamptz,
    rules_version          text,
    current_magnitude_band text,
    reuse_blocked          boolean not null default false,
    reuse_blocked_reason   text,
    updated_at             timestamptz not null default now()
);

create table if not exists decision_router.playbooks (
    id                  text primary key,
    pattern_key         text not null,
    case_type           text not null,
    name                text not null,
    version             integer not null default 1 check (version >= 1),
    conditions          jsonb not null,
    recommended_action  jsonb not null,
    rules_version       text not null,
    magnitude_band      text not null,
    approved_count      integer not null default 0 check (approved_count >= 0),
    verified_ok_count   integer not null default 0 check (verified_ok_count >= 0),
    verified_fail_count integer not null default 0 check (verified_fail_count >= 0),
    status              text not null default 'draft'
                        check (status in ('draft','pending_approval','active','suspended','retired')),
    approved_by         text,
    approved_at         timestamptz,
    valid_from          timestamptz,
    valid_until         timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint playbooks_pattern_version_key unique (pattern_key, version),
    -- V1: nenhum playbook fica ativo sem aprovação humana registrada
    constraint playbooks_active_requires_human_approval
        check (status <> 'active' or (approved_by is not null and approved_at is not null))
);

create index if not exists playbooks_pattern_status_idx on decision_router.playbooks (pattern_key, status);

alter table decision_router.case_routes   enable row level security;
alter table decision_router.pattern_stats enable row level security;
alter table decision_router.playbooks     enable row level security;

revoke all on schema decision_router from anon, authenticated;
revoke all on all tables in schema decision_router from anon, authenticated;
