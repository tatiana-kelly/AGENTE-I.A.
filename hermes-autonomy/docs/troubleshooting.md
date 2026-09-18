# Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `hermes cron list` avisa "Gateway is not running" | nenhum relógio disparando o cron | escolher opção em `installation.md` → "Relógio do cron" |
| `INSUFFICIENT_EVIDENCE` nos workflows do GitHub | `GITHUB_TOKEN` ausente no ambiente do Guardião | definir `GITHUB_TOKEN` (leitura de Actions) na conta que roda o tick |
| Falso `PARTIAL_EXECUTION` com marcador presente | log cumulativo recortado errado | usar `segment: since_run` (log com data) ou `last_block` + `block_end` (log sem data) |
| Incidente de janela antiga reaparece | não reaparece: fingerprint automação+janela é idempotente | `ha.py incidents --automation <id>` |
| Reparo "não executado: janela expirada" | janela mais antiga que `repair_window_hours` | comportamento esperado; a próxima execução agendada assume |
| "Reexecução exige idempotent=true" | automação não confirmada como idempotente | confirmar com a Tatiana e ajustar o registry |
| `CIRCUIT_BREAKER_OPEN` | ≥5 falhas em 24h | investigar a causa raiz; `ha.py circuit-reset <id>` após corrigir |
| Registry não carrega | erro de validação (mensagem lista o campo) | `ha.py registry --list` |
| Acentos quebrados no console | code page do Windows | `$env:PYTHONIOENCODING='utf-8'` |
| `Get-ScheduledTask falhou` | PowerShell restrito | rodar com o mesmo usuário das tarefas; checar ExecutionPolicy |

Diagnóstico de um incidente específico: `ha.py incident <id>` mostra os 12 passos, as evidências
EXPECTED vs ACTUAL, o ciclo de vida, as tentativas e a auditoria.
