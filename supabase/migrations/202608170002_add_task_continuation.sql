-- FASE 13: lineage and authenticated approval metadata for task continuation.

alter table public.ai_tasks
  add column if not exists continued_from_task_id uuid references public.ai_tasks(id) on delete set null,
  add column if not exists approval jsonb;

alter table public.ai_tasks
  drop constraint if exists ai_tasks_approval_shape_check;

alter table public.ai_tasks
  add constraint ai_tasks_approval_shape_check check (
    approval is null or (
      approval @> '{"approved": true}'::jsonb
      and approval->>'source' in ('n8n', 'api')
      and nullif(approval->>'approvedAt', '') is not null
      and jsonb_typeof(approval->'approvedMaxCostUsd') = 'number'
      and (approval->>'approvedMaxCostUsd')::double precision >= 0
    )
  );

create index if not exists ai_tasks_continued_from_idx
  on public.ai_tasks(continued_from_task_id)
  where continued_from_task_id is not null;
