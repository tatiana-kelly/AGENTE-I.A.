# Agentes

Os cinco agentes são módulos determinísticos orquestrados por `orchestrator.py`, executados pelo cron nativo
do Hermes. Cada ação registra o `agent` responsável no `audit_log` e no ciclo de vida do incidente.

| Agente | Módulo | Responsabilidade | Travas |
|---|---|---|---|
| `hermes-guardian` | `guardian.py` | SUPERVISÃO: janela esperada, execução, código de saída, duração, logs, saídas, banco/API, entrega; classifica | somente leitura |
| `hermes-diagnostician` | `diagnostician.py` | 12 passos: estado atual → última execução → último sucesso → logs → processo → arquivos → banco → API → autenticação → dependências → alterações recentes → histórico | sem evidência = `UNKNOWN_CAUSE` |
| `hermes-repair-agent` | `repair.py` | executa ação autorizada | ver matriz abaixo |
| `hermes-validator` | `validator.py` | REPAIR → RE-RUN → VERIFY → EXPECTED vs ACTUAL | não confia no retorno do reparo |
| `hermes-escalator` | `escalator.py` | mensagem acionável, imediato vs relatório, incidente raiz | dedupe + rate limit |

## Matriz de permissões do Reparador

| Risco | Ações | Execução automática |
|---|---|---|
| Baixo | `rerun_task`, `rerun_command`, `restart_task`, `cleanup_temp`, `validate_output` | sim, se autorizada no registry, `idempotent: true`, dentro da janela e sem circuito aberto |
| Médio | `adjust_timeout`, `switch_endpoint` | não no MVP (`max_repair_risk: low`) |
| Alto | `delete_data`, `alter_schema`, `rotate_credentials`, `modify_code`, `delete_files` | nunca — criar correção → testar → registrar → escalar |

Ordem das travas: ação existe → janela de reparo → circuit breaker → autorizada no registry → risco →
guarda de entrega → idempotência declarada → rate limit → DRY_RUN.

## Como criar um agente novo

1. Módulo em `hermes_autonomy/` com uma responsabilidade e sem efeitos colaterais fora do `Store`.
2. Registrar ações com `store.audit(agent, action, reason, result, ...)`.
3. Encadear no `Orchestrator.run()`.
4. Testes em `tests/` com `FakeTasks`/`FakeExecutor` (nunca tocar produção).
5. Documentar aqui e, se for consultável por um agente Hermes, criar uma Skill.
