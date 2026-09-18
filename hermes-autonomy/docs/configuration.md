# Configuração

Arquivo: `config/autonomy.json` (versionado). Precedência: defaults do código → arquivo → variáveis de ambiente →
flags da CLI (`--live`, `--fast`).

| Chave | Padrão | Significado |
|---|---|---|
| `dry_run` | `true` | detecta, diagnostica e **simula** o reparo. Env: `DRY_RUN` / `HERMES_AUTONOMY_DRY_RUN` |
| `autonomous_repair` | `false` | permite executar reparos. Env: `AUTONOMOUS_REPAIR`. Execução real exige `dry_run=false` **e** `autonomous_repair=true` |
| `max_repair_attempts` | 3 | tentativas antes de escalar |
| `max_repair_risk` | `low` | teto de risco das ações automáticas (high nunca executa) |
| `repair_window_hours` | 6 | janela mais antiga que isso não é reexecutada (a próxima execução agendada assume) |
| `retry_backoff_seconds` | `[0, 60, 180]` | espera entre tentativas |
| `validation.poll_seconds / timeout_seconds / settle_seconds` | 15 / 1800 / 5 | espera do Validador pela reexecução |
| `circuit_breaker.failure_threshold / window_hours / cooldown_hours` | 5 / 24 / 6 | falhas na janela que abrem o circuito, e por quanto tempo |
| `rate_limits.repairs_per_hour` | 10 | global |
| `rate_limits.repairs_per_automation_per_day` | 6 | por automação |
| `rate_limits.notifications_per_hour` | 6 | só canais externos |
| `rate_limits.http_calls_per_run` | 60 | checks HTTP por rodada |
| `defaults.grace_minutes / delay_tolerance_minutes / max_duration_minutes` | 20 / 10 / 60 | usados quando o registry não define |
| `notification.channels` | `["outbox"]` | `terminal`, `outbox`, `email_agent` (único canal externo — regra SAL) |
| `notification.external_enabled` | `false` | liga canais externos (decisão da Tatiana) |
| `notification.immediate_min_priority` | `P1` | P0/P1 e ação necessária = alerta imediato; resto vai ao relatório |
| `notification.email_agent.recipient` | `null` | ex.: `tatiana@salexpress.com.br` — usa o Email Agent oficial |
| `notification.dedupe_hours` | 12 | mesma notificação não repete dentro do intervalo |

Outras variáveis: `HERMES_AUTONOMY_HOME` (estado), `HERMES_AUTONOMY_REGISTRY`, `HERMES_AUTONOMY_CONFIG`,
`GITHUB_TOKEN` (habilita checagem dos workflows do GitHub; sem ele o status é `INSUFFICIENT_EVIDENCE`).

## Habilitar notificação real (exemplo — e-mail pelo Email Agent)

```json
"notification": {"channels": ["outbox", "email_agent"], "external_enabled": true,
                 "email_agent": {"path": "C:\\CENTRO-DE-AGENTES-IA", "recipient": "tatiana@salexpress.com.br"}}
```

Depois: `python -m hermes_autonomy install`.
