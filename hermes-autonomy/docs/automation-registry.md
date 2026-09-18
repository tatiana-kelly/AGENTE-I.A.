# automation_registry

Arquivo: `registry/automations.json`. Validado ao carregar (e por teste): campos obrigatórios, fontes,
ações conhecidas, ids únicos e **ausência de segredo literal**.

## Campos

| Campo | Obrigatório | Descrição |
|---|---|---|
| `id`, `name`, `description` | id/name | identificação |
| `source` | sim | `windows_task` · `github_actions` · `command` · `hermes_cron` |
| `task_name` / `github` / `command` | conforme source | `\\Nome Da Tarefa` · `owner/repo:workflow.yml` · lista de argumentos |
| `schedule` | sim | `daily`, `interval`, `monthly`, `cron` (`utc: true`), `event` — ver `timeutil.py` |
| `grace_minutes` | não | quanto esperar após o horário antes de julgar |
| `delay_tolerance_minutes` | não | atraso aceito antes de `DELAYED_EXECUTION` |
| `max_duration_minutes` | não | acima disso, "rodando" vira `TASK_HUNG` |
| `checks` | não | evidências (abaixo) |
| `expected_outputs`, `dependencies`, `success_criteria`, `failure_criteria` | não | documentação + agrupamento de causa raiz (`dependencies[0]`) |
| `allowed_recovery_actions` | não | subconjunto de `rerun_task`, `rerun_command`, `restart_task`, `cleanup_temp`, … |
| `idempotent` | não | `true` libera reexecução; `false`/`"unverified"` bloqueia |
| `rerun_guard` | não | `"no_delivery"`: só reexecuta se a entrega (e-mail) NÃO aconteceu |
| `repair_window_hours` | não | sobrescreve o global |
| `risk_level`, `criticality` | não | `low/medium/high` · `critical/high/medium/low` (prioridade) |
| `impact`, `owner`, `enabled`, `notes` | não | |
| `instances` | não | expande a entrada em N automações (`suffix`, `label`, `vars`, `schedule`) |

## Checks

```json
{"type": "file", "kind": "log|output|data|delivery", "path": "C:/x/log_{date:%Y%m%d}.log",
 "glob": "C:/x/*.csv", "fresh": true, "min_bytes": 1, "json_valid": false,
 "segment": "tail|since_run|last_block", "block_end": "^regex$",
 "success_patterns": ["=== fim"], "failure_patterns": ["Traceback|ERROR"]}
{"type": "http_status", "kind": "dependency", "url": "{env:SUPABASE_URL}/rest/v1/", "headers": {"apikey": "{env:SUPABASE_ANON_KEY}"}, "expect_status": [200]}
{"type": "http_freshness", "kind": "data", "url": "{env:SUPABASE_URL}/rest/v1/tabela?select=updated_at&order=updated_at.desc&limit=1", "headers": {...}, "field": "updated_at"}
{"type": "command", "kind": "output", "command": ["python", "check.py"], "expect_exit": 0}
```

`kind` → critério: log → `PROCESS_STARTED/PROCESS_FINISHED`; output → `OUTPUT_EXISTS/OUTPUT_VALID`;
data → `DATA_UPDATED`; delivery → `DELIVERY_COMPLETED`; dependency → `DEPENDENCY_OK`.
Placeholders: `{date:%fmt}` (data da janela), `{env:NOME}`, variáveis de `instances`.

## Como adicionar uma automação

1. `python -m hermes_autonomy discover` (tarefas fora do registry).
2. Escreva a entrada com evidências reais (marcador de sucesso/erro do log).
3. `python -m hermes_autonomy registry --list` → "registry OK".
4. `python -m hermes_autonomy health --only <id> -v`.
5. `python -m hermes_autonomy install`.

Skill Hermes equivalente: `register-automation`.
