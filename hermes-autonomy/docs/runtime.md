# Runtime — ambiente atual é DESENVOLVIMENTO/MVP

| Componente | Onde roda hoje | Natureza |
|---|---|---|
| Hermes Agent + Hermes Autonomy | notebook Windows 10 da Tatiana (`%LOCALAPPDATA%\hermes`) | **dev/MVP** |
| SAL Intelligence OS | local (`AGENTE-I.A\sal-intelligence-os`, SQLite padrão; schema `decision_router` já no Supabase `sal-ai-orchestrator`, vazio) | **dev/MVP** |
| AI Orchestrator | Vercel + Supabase `sal-ai-orchestrator` | serviço gerenciado |
| Automações supervisionadas | Agendador do Windows no mesmo notebook + GitHub Actions | produção atual (fora do escopo do Hermes) |

## O que NÃO assumir

- Que o Windows vá ser o runtime 24/7. Notebook desliga, suspende e troca de rede. Não há gateway Hermes rodando
  nem ticker instalado (**autonomia 24/7 desligada**).
- Que `%LOCALAPPDATA%` e o SQLite local sejam armazenamento durável. São memória técnica de desenvolvimento.
- Que a "porta" do SAL OS local (FastAPI em dev) seja um endpoint estável para integração.

## Partes específicas de Windows (isoladas)

- `adapters.WindowsTaskProvider` e `SystemExecutor.run_task/stop_task` (PowerShell `*-ScheduledTask`).
- `ha.py ticker` (Agendador do Windows como gatilho do `hermes cron tick`).
- Caminhos `C:/...` no registry, que vêm das próprias automações e mudam se elas mudarem de host.

O motor (guardian, diagnostician, repair, validator, escalator, store, contrato) é Python stdlib, sem dependência de SO.

## Caminho para produção (decisão futura, HUMAN_REQUIRED)

1. Escolher um host sempre ligado (VM/servidor Linux, ou container) para o Hermes. O gateway do Hermes tem instalação
   nativa como serviço `systemd`/`launchd` (`hermes gateway install`), e o cron roda dentro dele. Não é preciso ticker.
2. Automações que continuarem no Windows precisam de um coletor local (este adapter) que publique o estado. Automações
   migradas passam a ter adapter do novo host (ex.: systemd timers, GitHub Actions).
3. Memória técnica: SQLite serve para um nó. Com mais de um nó, um Postgres técnico. Decisão só nessa hora, sem misturar
   com a memória empresarial do SAL OS.
4. Transporte do `AUTOMATION_INCIDENT` e segredo HMAC entregues pelo ambiente (nunca em arquivo versionado).
