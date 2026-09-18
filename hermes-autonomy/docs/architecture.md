# Arquitetura

## Decisões (adaptação do PRP à realidade auditada)

| Tema | Decisão | Por quê |
|---|---|---|
| Runtime/agendamento | **cron nativo do Hermes** em modo `--no-agent --script` | PRP: não duplicar scheduler; `--no-agent` roda o script sem LLM (custo zero) e entrega stdout |
| Onde as automações rodam | Agendador do Windows (30 ativas) + GitHub Actions (3) | É o que existe; o Guardião lê, não substitui |
| Motor | Python stdlib, determinístico | roda no Python do próprio Hermes (3.11) e no do sistema (3.12); sem dependências novas |
| Registry | JSON versionado no Git (`registry/automations.json`) | revisável em PR, validado por teste; expansão por `instances` evita repetição |
| Memória/auditoria | SQLite local (`%LOCALAPPDATA%\hermes\autonomy\autonomy.db`) | um arquivo, transacional, sem servidor; o Supabase não recebe dado operacional desta camada |
| Notificação | `NotificationService` → outbox (sempre) + Email Agent oficial (opt-in) | regra SAL: notificação só via Email Agent; sem segundo sistema de mensagens (ver `alignment-sal-os.md`) |
| LLM | fora do caminho crítico | diagnóstico por evidência catalogada; Skills permitem que um agente Hermes consulte/explique |

## Componentes

```text
hermes-autonomy/
  hermes_autonomy/
    guardian.py        EXPECTED vs ACTUAL, classificação de incidentes (somente leitura)
    diagnostician.py   12 passos de investigação, causa + evidência + confiança
    repair.py          matriz de permissões, idempotência, circuit breaker, rate limit, DRY_RUN
    validator.py       reverificação completa sobre o que o reparo escreveu (baseline por offset/mtime)
    escalator.py       mensagem acionável; imediato vs relatório; incidente raiz
    orchestrator.py    fluxo central + ciclo de vida + agrupamento por causa raiz
    notify.py          canais (terminal, outbox, email_agent)
    report.py          HERMES AUTOMATION HEALTH diário
    store.py           SQLite: incidents, incident_events, repair_attempts, audit_log, notifications,
                       circuit, skill_candidates, runs, checks
    adapters.py        Agendador do Windows (PowerShell, 1 chamada por rodada), GitHub API, HTTP, subprocess
    knowledge.py       padrões de causa e códigos do Agendador
    timeutil.py        janelas esperadas (daily, interval, monthly, cron UTC, event)
    redact.py          redação de segredos
    canary.py          automação-sandbox para provas controladas
    install.py         integração com o Hermes (app, wrappers, skills, cron)
  registry/            automations.json (real) · sandbox.json (canário)
  config/autonomy.json
  skills/              Skills Hermes (automation-guardian, incident-memory, register-automation)
  tests/               41 testes
```

## Evidência (critério de SUCCESS)

Uma execução só é `SUCCESS` quando todos os critérios verificáveis passam:
`PROCESS_STARTED`, `ON_TIME`, `PROCESS_FINISHED` (código + marcador de fim no log), `OUTPUT_EXISTS`,
`OUTPUT_VALID`, `DATA_UPDATED`, `DELIVERY_COMPLETED`, `DEPENDENCY_OK` — conforme o que o registry declara.
Sem nenhuma evidência verificável → `INSUFFICIENT_EVIDENCE` (nunca "parece que funcionou").

Logs cumulativos são recortados na execução certa: `since_run` (carimbo no início **ou** carimbo de fim tipo
`Fim dd/mm/aaaa hh:mm`) e `last_block` (logs sem data, delimitados pelo marcador final). Na validação
pós-reparo o recorte é exato: lê só os bytes escritos após o baseline.

## Classificação

`MISSED_EXECUTION`, `DELAYED_EXECUTION`, `FAILED_EXECUTION`, `PARTIAL_EXECUTION`, `MISSING_OUTPUT`,
`INVALID_OUTPUT`, `DATA_NOT_UPDATED`, `DELIVERY_FAILURE`, `AUTHENTICATION_FAILURE`, `API_FAILURE`,
`DEPENDENCY_FAILURE`, `RESOURCE_FAILURE`, `UNKNOWN_FAILURE`, `RECURRING_FAILURE`, `ROOT_CAUSE_INCIDENT`.

## Ciclo de vida

`DETECTED → CLASSIFIED → DIAGNOSING → DIAGNOSED → REPAIRING → VALIDATING → RESOLVED | ESCALATED`
com desfecho: `AUTO_RECOVERED`, `ALREADY_OK`, `DELAY_RECORDED`, `ESCALATED`, `ESCALATED_WITH_ACTION_REQUIRED`,
`CIRCUIT_BREAKER_OPEN`, `DRY_RUN_PLANNED`, `RATE_LIMITED`.

## Event-driven

Além do polling a cada 30 min: `ha.py event <automation_id> --message "..."` roda o ciclo na hora só para
aquela automação. Qualquer `.bat` existente pode chamar isso no ramo de erro (ver `operations.md`);
o Hermes também aceita `hermes webhook` apontando para o mesmo comando.
