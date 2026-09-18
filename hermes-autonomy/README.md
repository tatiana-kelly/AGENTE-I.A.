# Hermes Autonomy — Guardião Autônomo das Automações

Camada autônoma de **confiabilidade e recuperação** sobre as automações que já existem (Agendador do Windows,
GitHub Actions, scripts). Não é dashboard e não recria nenhuma automação: supervisiona o que DEVERIA ter
acontecido, prova o que aconteceu, diagnostica, corrige o que é seguro, valida e só chama a Tatiana quando precisa.

```text
Hermes cron (nativo, --no-agent) ─► GUARDIAN ─► incidente? ─► DIAGNOSTICIAN ─► reparo autorizado?
                                                                  ├─ não ─► ESCALATOR
                                                                  └─ sim ─► REPAIRER ─► VALIDATOR ─► ok? ─► RESOLVED
                                                                                              └─ não ─► retry (≤3) ─► ESCALATOR
```

- **Claude Code** = engenheiro (constrói, testa, documenta, mantém este código).
- **Hermes Agent v0.21.2** = runtime (cron nativo `--no-agent`, scripts, Skills).
- **Fronteira:** Hermes = confiabilidade das AUTOMAÇÕES · SAL Intelligence OS = decisão sobre desvios do NEGÓCIO ·
  AI Orchestrator = runtime técnico de IA. Ver [alignment-sal-os](docs/alignment-sal-os.md).
- **Motor** = Python stdlib puro (sem dependências), determinístico — sem LLM no caminho crítico, custo zero de tokens.

## Início rápido

```powershell
cd C:\Users\tatiana.silva\AGENTE-I.A\hermes-autonomy
python -m hermes_autonomy health            # EXPECTED vs ACTUAL agora (somente leitura)
python -m hermes_autonomy tick              # ciclo completo (DRY_RUN por padrão)
python -m hermes_autonomy report            # relatório diário consolidado
python -m hermes_autonomy status            # modo, última rodada, incidentes, cron Hermes
python -m unittest discover -s tests        # 41 testes (inclui os 12 do PRP)
python -m hermes_autonomy demo recover --live --fast --state-dir %LOCALAPPDATA%\hermes\autonomy-sandbox\x
```

Instalado no Hermes: `python "%LOCALAPPDATA%\hermes\autonomy\app\ha.py" <comando>`.

## Estado atual

| Item | Situação |
|---|---|
| Modo | `DRY_RUN=true`, `AUTONOMOUS_REPAIR=false` (nada em produção é alterado) |
| Automações no registry | 38 (30 supervisionadas, 8 desabilitadas catalogadas) |
| Cron Hermes | `hermes-autonomy-guardian` (30 min) e `hermes-autonomy-daily-report` (18:00) |
| Disparo automático | **pendente de decisão** — gateway Hermes parado; ver `docs/operations.md` → "Relógio do cron" |
| Notificação externa | desligada (outbox local) — decisão de canal em `docs/configuration.md` |

## Documentação

[architecture](docs/architecture.md) · [installation](docs/installation.md) · [configuration](docs/configuration.md) ·
[automation-registry](docs/automation-registry.md) · [agents](docs/agents.md) · [skills](docs/skills.md) ·
[memory](docs/memory.md) · [security](docs/security.md) · [recovery](docs/recovery.md) ·
[troubleshooting](docs/troubleshooting.md) · [operations](docs/operations.md) · [auditoria 18/09](docs/audit-2026-09-18.md) ·
[alinhamento SAL OS](docs/alignment-sal-os.md) · [hardening fase 2](docs/hardening-phase2.md) · [runtime](docs/runtime.md)
