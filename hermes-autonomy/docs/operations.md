# Operação

Atalho: `$ha = "$env:LOCALAPPDATA\hermes\autonomy\app\ha.py"` e depois `python $ha <comando>`.

| Objetivo | Comando |
|---|---|
| **start** | `python $ha start` (retoma cron jobs) + relógio ativo (`ticker install --yes` ou gateway) |
| **stop** | `python $ha stop` · emergência geral do Hermes: `hermes pause` |
| **status** | `python $ha status` |
| **health** | `python $ha health` (`-v` evidências, `--only id1,id2`) |
| **logs** | `python $ha logs --limit 50` · execuções do cron: `hermes cron runs fdddd6004c02` |
| **dry-run** | `python $ha tick` (padrão) |
| **test** | `cd AGENTE-I.A\hermes-autonomy; python -m unittest discover -s tests` |
| relatório | `python $ha report` · `--send` usa os canais configurados |
| incidentes | `python $ha incidents` · `incident <id>` · `history <automation> --cause <CAUSA>` |
| descobrir automações novas | `python $ha discover` |
| provas controladas | `python -m hermes_autonomy demo recover|escalate|credential|partial --live --fast --state-dir <sandbox>` |
| relógio do cron | `python $ha ticker status|install --yes|remove --yes` |

## Rotina

- A cada 30 min: `hermes-autonomy-guardian` (tick). Silencioso quando tudo está OK.
- 10:00: `hermes-autonomy-daily-report` (HERMES AUTOMATION HEALTH).
- P0/P1 e "ação necessária": alerta imediato (outbox; canais externos se habilitados).

## Event-driven (opcional, sem alterar automações agora)

Para reduzir a latência de detecção, um `.bat` pode avisar o Guardião no ramo de erro:

```bat
if errorlevel 1 python "%LOCALAPPDATA%\hermes\autonomy\app\ha.py" event torre-importar-ssw-1200 --message "rc=%errorlevel%"
```

(Alterar os `.bat` das automações é decisão da Tatiana — o PRP proíbe modificar automações nesta fase.)
