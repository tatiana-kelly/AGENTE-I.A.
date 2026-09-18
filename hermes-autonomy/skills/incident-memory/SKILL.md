---
name: incident-memory
description: Consulta a memória de incidentes das automações — "essa automação já teve esse problema?", "como resolvemos da última vez?", detalhes de um incidente, auditoria e Skills candidatas.
version: 0.1.0
author: Claude Code (AGENTE-I.A / hermes-autonomy)
license: proprietary
platforms: [windows]
metadata:
  hermes:
    tags: [incidents, memory, postmortem, audit]
    category: autonomy
---

# Incident Memory

Memória persistente (SQLite) de todo incidente: automação, janela esperada, tipo, causa, evidências, ações,
resultado, tempo de recuperação, tentativas e solução. Base: `%LOCALAPPDATA%\hermes\autonomy\autonomy.db`.

Comandos (`python "%LOCALAPPDATA%\hermes\autonomy\app\ha.py" ...`):

| Pergunta | Comando |
|---|---|
| Essa automação já teve esse problema? | `history <automation_id> --cause <CAUSA>` |
| Como resolvemos da última vez? | `history <automation_id> --cause <CAUSA>` (linha "Última solução validada") |
| Lista de incidentes | `incidents [--automation ID] [--cause CAUSA] [--limit N]` |
| Tudo sobre um incidente (12 passos do diagnóstico, evidências, ciclo de vida, tentativas, auditoria) | `incident <INC-...>` |
| Log de auditoria (quem fez o quê) | `logs --limit 50` |
| Soluções validadas candidatas a virar Skill | `skills` |

Causas catalogadas: `NETWORK_TIMEOUT`, `CONNECTION_FAILED`, `HTTP_5XX`, `RATE_LIMITED`, `AUTH_EXPIRED`,
`AUTH_DENIED`, `CREDENTIAL_MISSING`, `MODULE_MISSING`, `FILE_NOT_FOUND`, `DISK_FULL`, `FILE_LOCKED`,
`BROWSER_TIMEOUT`, `GIT_PUSH_REJECTED`, `EMPTY_SOURCE`, `TASK_ACCESS_DENIED`, `TASK_HUNG`, `TASK_OVERLAP`,
`TASK_DISABLED`, `TASK_NOT_FOUND`, `TASK_NOT_TRIGGERED`, `SCRIPT_EXIT_NONZERO`, `UNKNOWN_CAUSE`.

## Regras

- Responda com os dados do banco (datas, ids, evidências) — não resuma de memória.
- Skill candidata é só sugestão: publicar uma Skill nova exige revisão da Tatiana (MVP).
- A memória nunca guarda segredos: todo texto passa por redação automática antes de ser gravado.
