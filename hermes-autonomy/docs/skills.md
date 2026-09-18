# Skills

## Criadas (publicadas no Hermes em `%LOCALAPPDATA%\hermes\skills\autonomy\`)

| Skill | Uso |
|---|---|
| `automation-guardian` | "as automações rodaram?", saúde, ciclo completo, relatório |
| `incident-memory` | "já teve esse problema?", "como resolvemos?", detalhe de incidente, auditoria |
| `register-automation` | colocar uma automação nova sob supervisão |

As Skills sugeridas no PRP (`diagnose-api-failure`, `retry-failed-job`, `validate-output`,
`check-supabase-update`, `check-process-health`, `inspect-github-workflow`, `inspect-cron`, …) foram
implementadas como **capacidades do motor**, não como Skills separadas — o PRP pede "não criar Skills
desnecessárias":

| Sugerida | Onde vive |
|---|---|
| check-process-health / inspect-cron | `adapters.WindowsTaskProvider` + `guardian._task_evidence` |
| inspect-github-workflow | `adapters.GithubRunsProvider` |
| validate-output / validate-data-integrity | checks `file` (`min_bytes`, `json_valid`, padrões) |
| check-supabase-update | check `http_freshness` (PostgREST) |
| check-email-delivery | check `kind: delivery` |
| diagnose-api-failure / recover-authentication | `knowledge.CAUSE_PATTERNS` + `diagnostician` |
| retry-failed-job | `repair.rerun_task/rerun_command` + `validator` |
| incident-reporting | `escalator` + `report` |

## Reutilizadas

- `integrar-email-agent` (Claude Code) — contrato do Email Agent usado pelo canal `email_agent`.
- Skills nativas do Hermes permanecem intocadas.

## Aprendizado (Skill candidata)

Toda recuperação validada gera/atualiza uma linha em `skill_candidates` (causa → ação → automação,
contador de sucessos). `ha.py skills` lista. No MVP **não há publicação automática**: a Tatiana decide
promover uma candidata a Skill (ex.: `NETWORK_TIMEOUT → rerun_task` validado 5x).

## Como adicionar uma Skill

1. Criar `skills/<nome>/SKILL.md` com o frontmatter do Hermes (`name`, `description`, `version`, `metadata.hermes`).
2. `python -m hermes_autonomy install` (publica em `skills/autonomy/`).
3. Conferir: `hermes skills list | findstr <nome>`.
