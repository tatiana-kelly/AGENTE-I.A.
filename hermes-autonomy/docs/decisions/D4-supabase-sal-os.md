# D4 — Supabase da memória/eventos do SAL Intelligence OS

**Status:** CONFIRMADA pela Tatiana (Fase 3, 18/09/2026)

## Decisão

Memória empresarial/decisional **e** eventos do SAL OS → projeto Supabase **`sal-ai-orchestrator`**
(`zkwfupxztxczeadrlsri`, sa-east-1). **Nenhum banco novo.**

## Contexto (verificado, somente leitura)

- O schema `decision_router` (`case_routes`, `pattern_stats`, `playbooks`) já está aplicado nesse projeto
  (migration `20260917180008_decision_router_memory`, RLS on, 0 linhas). O projeto também hospeda a persistência do AI
  Orchestrator (`ai_tasks`, `ai_runs`, `ai_evidence`, `ai_projects`, `ai_project_permissions`) e o
  `ai_agent_runs`/`ai_agent_run_audit`.
- `relatorios-raw` continua sendo a **fonte operacional** que o SAL OS apenas **lê** (`operational_connector.py`).

## Consequências

1. Eventos futuros do SAL OS (inclusive o que ele derivar de `AUTOMATION_INCIDENT`) vão para um **schema próprio do SAL OS**
   dentro de `sal-ai-orchestrator`. O SAL OS é dono e decide; nada disso é criado nesta fase.
2. A memória técnica do Hermes **permanece fora** (SQLite local). Não há sincronização nem cópia.
3. O SAL OS deve usar credencial própria de escopo mínimo, nunca o `service_role` do Orchestrator.
4. Pendência de documentação no SAL OS (repo de outro dono de código, não alterada aqui): as docstrings que ainda dizem
   "D4 pendente" (`decision_router/memory/__init__.py`, `postgres.py`, `repository.py`, `recorder.py`) devem apontar para
   esta decisão.
