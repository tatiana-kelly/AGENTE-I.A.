# Recuperação e rollback

## Como a recuperação automática funciona

1. Guardião detecta desvio numa janela → incidente (`DETECTED`, `CLASSIFIED`).
2. Diagnosticador aponta causa com evidência. Causa **transitória** (timeout, 5xx, 429, conexão, arquivo
   bloqueado, tarefa travada, gatilho perdido) → ação automática candidata. Causa **não transitória**
   (credencial, acesso negado, módulo ausente, disco) → `ESCALATED_WITH_ACTION_REQUIRED`.
3. Reparador aplica as travas (janela, circuito, registry, risco, entrega, idempotência, rate limit, DRY_RUN).
4. Antes de agir: **o estado esperado já está presente?** Se sim → `ALREADY_OK` (nada é reexecutado).
5. Baseline dos arquivos → dispara a ação → Validador espera e reverifica **só o que foi escrito depois**.
6. `SUCCESS` → `RESOLVED/AUTO_RECOVERED`, solução gravada, Skill candidata registrada.
   Falha → nova tentativa (backoff) até `max_repair_attempts` → `ESCALATED` com tudo que foi tentado.

## Habilitar reparo real (somente baixo risco)

```powershell
# 1) Confirmar idempotência das automações que podem ser reexecutadas (registry: idempotent true)
# 2) config/autonomy.json → "dry_run": false, "autonomous_repair": true
python -m hermes_autonomy install
```

Ou pontualmente: `python -m hermes_autonomy tick --live --only <id>`.

## Rollback

| O quê | Comando |
|---|---|
| Voltar a só observar | `config/autonomy.json` → `"dry_run": true` + `install` |
| Pausar o Guardião | `python ha.py stop` (pausa os cron jobs) · emergência: `hermes pause` |
| Retomar | `python ha.py start` · `hermes resume` |
| Desinstalar do Hermes | `python ha.py uninstall` (remove cron jobs, wrappers, Skills e app; **preserva** o histórico) |
| Remover o ticker | `python ha.py ticker remove --yes` |
| Reabrir automação bloqueada | `python ha.py circuit-reset <id>` |
| Código | `git revert` dos commits `feat(hermes-autonomy)` na branch `feat/hermes-autonomy` |

Nenhuma automação existente foi modificada por este projeto — rollback não exige restaurar nada nelas.
