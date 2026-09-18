# Custos observados — Fase 5G (insumo para o futuro CASE_BUDGET)

Somente medição. Nenhum limite foi alterado. Caso 100% sintético (`synthetic_test=true`), rota fictícia, 2026-09-18.

## Estrutura de um caso MULTI_AGENT

| Etapa | IA? | Provider/modelo | Limite por chamada | Limite do job |
|---|---|---|---|---|
| investigador | sim | Anthropic `claude-sonnet-5` | US$ 1 (contrato); cap efetivo agent-run US$ 0,40 | US$ 3 |
| transferencia | sim | Anthropic `claude-sonnet-5` | US$ 1 (contrato); cap efetivo agent-run US$ 0,40 | US$ 3 |
| consolidação | não (determinística) | — | — | — |
| revisão consolidada | sim | OpenAI (revisor ≠ autor) | US$ 1 | US$ 3 |

Correções: 0 (`max_correction_attempts=0`). Retry HTTP oculto: nenhum (`maxHttpAttempts=1`).
Não existe teto por caso: a soma dos orçamentos dos 3 jobs é US$ 9.

## Medições reais

| Tentativa | Etapa | Tokens entrada / saída / total | Reservado | Latência | Resultado |
|---|---|---|---|---|---|
| 1 | investigador | 8.568 / 6.863 / 15.431 | US$ 0,40 | 62,5 s | 422 saída fora do contrato |
| 1 | transferencia | 8.402 / 6.088 / 14.490 | US$ 0,40 | 55,8 s | 422 saída fora do contrato |
| 1 | revisão | — | — | — | não executada |
| 2 | investigador | 8.744 / 5.046 / 13.790 | US$ 0,40 | 47,8 s | sucesso |
| 2 | transferencia | 8.578 / 5.847 / 14.425 | US$ 0,40 | 54,2 s | sucesso |
| 2 | revisão (`gpt-5.6-sol`) | 9.890 / 638 / 10.528 | US$ 1,00 | 16,3 s | REJECTED → NEEDS_HUMAN |

- Tentativa 2 (caso completo): 38.743 tokens, US$ 1,80 reservados, 122,9 s.
- Tentativas 1 + 2: 68.664 tokens, US$ 2,60 reservados.
- Custo real: `unknown` em todas as chamadas (o provider não informa; nunca estimado como real).

## Observações para definir o CASE_BUDGET

1. A reserva por caso segue os caps por chamada, não o consumo: a revisão reservou US$ 1,00 para cerca de 10,5 mil tokens.
2. Uma falha de contrato gasta o mesmo que um sucesso (tentativa 1): o teto por caso deve contar tentativas falhas.
3. Um ciclo de correção, se for adotado, acrescenta até uma chamada de autor por agente reprovado.
4. Os agentes consomem cerca de 8,5 mil tokens de entrada por chamada: contexto autorizado, definição do agente e evidência.
