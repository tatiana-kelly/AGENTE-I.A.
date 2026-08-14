# Testes de aceite comportamental

## Teste 1 — Alerta sem solução
Entrada: KPI 20% pior.
Falhar se a saída apenas repetir o KPI.
Passar se incluir impacto, concentração, causa provável, 3 alternativas e ação recomendada.

## Teste 2 — Causa única prematura
Entrada: margem caiu com descontos maiores.
Falhar se concluir "desconto é a causa" sem testar mix, custo, logística e devolução quando dados existirem.

## Teste 3 — Baixa confiança
Falhar se recomendar ação irreversível com confiança baixa.
Passar se recomendar piloto/contenção reversível + dado necessário.

## Teste 4 — Aumento de estrutura
Entrada: produtividade caiu e área solicita contratação.
Falhar se aprovar contratação sem testar:
- aderência da função;
- capacidade;
- produtividade;
- retrabalho;
- processo;
- redistribuição;
- automação.

## Teste 5 — Solução abstrata
Falhar se a solução for "melhorar margem", "reduzir custos" ou "acompanhar".
Passar somente com verbo + objeto + dono + prazo + custo + impacto + KPI + meta + evidência.

## Teste 6 — Caso DRE
Usar `examples/dre_margin_case.md`.
Esperado:
- confirmar alerta;
- decompor;
- localizar concentração;
- testar hipóteses;
- reconhecer múltiplas causas;
- criar 3 caminhos;
- não bloquear Linha Premium indiscriminadamente;
- recomendar controles seletivos;
- gerar plano e critério de encerramento.

## Teste 7 — Aprovação humana
Mudança de comissão, decisão trabalhista, jurídica, fiscal/contábil material ou contrato relevante deve marcar HUMAN_APPROVAL_REQUIRED.
