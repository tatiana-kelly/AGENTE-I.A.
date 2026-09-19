# Instalação

Pré-requisitos (já presentes na máquina auditada): Hermes Agent ≥ 0.21 (`hermes --version`), Python ≥ 3.11,
Windows PowerShell 5.1. Nenhum `pip install` é necessário.

```powershell
cd C:\Users\tatiana.silva\AGENTE-I.A\hermes-autonomy
python -m unittest discover -s tests          # 41 testes devem passar
python -m hermes_autonomy registry --list     # "registry OK"
python -m hermes_autonomy health              # somente leitura
python -m hermes_autonomy install             # idempotente
```

`install` faz:

1. copia `hermes_autonomy/`, `registry/`, `config/` e `ha.py` para `%LOCALAPPDATA%\hermes\autonomy\app`
   (o runtime não depende da branch em que o repositório estiver);
2. grava os wrappers `hermes_autonomy_tick.py` e `hermes_autonomy_report.py` em `%LOCALAPPDATA%\hermes\scripts`
   (o `hermes cron --script` só aceita scripts dessa pasta);
3. publica as Skills em `%LOCALAPPDATA%\hermes\skills\autonomy\`;
4. cria (se não existirem) os cron jobs nativos:
   - `hermes-autonomy-guardian` — `every 30m`, `--no-agent`, `--deliver local`
   - `hermes-autonomy-daily-report` — `0 10 * * *`, `--no-agent`, `--deliver local`

Alterou código ou registry? Rode `install` de novo — é assim que a cópia do Hermes é atualizada
(mesma convenção dos agentes globais: edita na fonte, recopia).

## Relógio do cron (decisão da Tatiana)

Os cron jobs do Hermes só disparam com **um** destes:

| Opção | Comando | Efeito colateral |
|---|---|---|
| A. Ticker mínimo (recomendado) | `python ha.py ticker install --yes` | tarefa `Hermes - Cron Tick` no Agendador roda `hermes cron tick` a cada 15 min; nada mais sobe |
| B. Gateway Hermes | `hermes gateway run` (manter aberto) | também conecta as plataformas de mensagem configuradas (WhatsApp, Mattermost, WeCom, …) e o bot passa a responder |
| C. Manual | `hermes cron run <id>` + `hermes cron tick` | nada automático |

Remover o ticker: `python ha.py ticker remove --yes`.
