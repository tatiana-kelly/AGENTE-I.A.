# FASE 19 — Teste Real (READ_ONLY, baixo risco)

**Data:** 2026-08-13
**Comando:** `node --env-file=.env scripts/real-test.mjs "<tarefa>"`
**Modo:** `READ_ONLY`, `DRY_RUN=true` — nada foi/poderia ser alterado.

## O que foi testado

Rodei a tarefa completa (classificação → roteamento → plano → gate de segurança → chamada real ao provider → tratamento de erro → observability) contra a API real da Anthropic, usando a chave já configurada em `.env`.

## Resultado

A pipeline funcionou corretamente ponta a ponta:
- Classificação: `skills: ["automation"]`, nenhum sinal de escrita → tratado como leitura.
- Roteamento: `primary: anthropic`, `reviewer: openai` (openai não registrado, seria pulado com segurança se chegasse a essa etapa).
- Gate de segurança: permitiu a execução (ação de leitura, sempre permitida mesmo em `READ_ONLY`).
- Chamada real ao provider: **falhou com erro estruturado, não com crash** — `HTTP 400`: *"Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."*
- O erro foi capturado, reportado em `results[0]` como `status: "error"` com a razão exata, e logado via Observability — nada quebrou, nada foi perdido, nenhuma exceção não tratada.

## Conclusão

**A engenharia está correta** — classificação, roteamento, plano, gate de segurança, chamada HTTP e tratamento de erro funcionaram exatamente como desenhado. O que bloqueou foi a **conta da Anthropic associada a essa chave estar sem saldo/crédito** — não é um bug no orchestrator.

`healthCheck()` (que só lista modelos, sem custo) tinha funcionado antes porque não depende de saldo — só a chamada real de `analyze()` (que consome créditos) expôs o problema.

## Próximo passo

Para produzir uma resposta real, é preciso adicionar créditos/billing na conta da Anthropic dona dessa chave (ou trocar por uma chave de uma conta com saldo). Depois disso, `node --env-file=.env scripts/real-test.mjs` reproduz o mesmo teste sem precisar reescrever nada.
