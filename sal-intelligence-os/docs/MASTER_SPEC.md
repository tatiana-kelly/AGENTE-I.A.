# SAL Intelligence OS — Especificação Mestre

## 1. Visão
Criar uma central de inteligência operacional e executiva para uma transportadora de carga fracionada.
A empresa já possui dados, KPIs e dashboards. O objetivo é transformar essa base em **decisões cirúrgicas**.

### O produto deve responder
- Qual é o maior desvio?
- Qual é o maior desvio em valor absoluto?
- Onde ele nasce?
- Por que está acontecendo?
- Quanto custa não agir?
- Qual é a causa mais provável?
- Quais hipóteses alternativas existem?
- Qual ponto específico deve receber esforço?
- Quais 3 ações são possíveis?
- Qual entrega o maior resultado com menor esforço?
- Quem deve agir?
- Em quanto tempo?
- Como provar que funcionou?

## 2. Escopo de domínio
Cobrir, progressivamente:
- carga fracionada;
- coleta;
- transferência;
- entrega;
- armazenagem;
- produtividade;
- qualidade/farmacêutico/RDC;
- gerenciamento de riscos;
- custos;
- orçamento;
- DRE;
- ROI/payback;
- comercial;
- faturamento;
- financeiro;
- RH;
- liderança;
- departamento pessoal;
- jurídico;
- fiscal;
- contábil;
- perdas;
- ressarcimentos;
- compras;
- TI/dados;
- engenharia/processos;
- auditoria;
- crises;
- conflitos;
- continuidade.

## 3. Arquitetura de inteligência
### Camada A — Detecção
Identifica anomalias, tendências, recorrências, concentração e oportunidades.

### Camada B — Investigação
Agente Investigador valida o fenômeno e decompõe a causa.

### Camada C — Especialistas
O coordenador chama somente os especialistas relevantes.

### Camada D — Contraditório
Agente Provocador tenta derrubar a hipótese e identificar efeito de segunda ordem.

### Camada E — Priorização
Compara impacto × esforço × risco × prazo × confiança.

### Camada F — Decisão
Conselheiro Executivo converte análise em fila de decisões.

### Camada G — Soluções e Ações Práticas
Recebe diagnóstico validado e produz contenção, correção estrutural e otimização, cada uma com ação exata, dono, prazo, custo, impacto, risco, KPI, meta, evidência e contingência.

### Camada H — Execução
Transforma decisão aprovada em ação, dono, prazo, meta e evidência.

### Camada I — Aprendizado
Registra previsão, decisão, execução e resultado real para calibrar análises futuras.

## 4. Tipos de inteligência horizontal
Além de agentes por área, o sistema deve possuir investigações transversais:

### Onde estamos perdendo dinheiro?
Cruzar DRE, custos, clientes, filial, operação, perdas, horas extras, terceiros e faturamento.

### Capacidade e produtividade
Cruzar pessoas, galpão, veículos, volume, entregas, horas, aderência à função, SLA e custo.

### Cliente destruidor de valor
Cruzar receita, tabela, descontos, coleta, transferência, entrega, reentrega, devolução, ressarcimento, atendimento e prazo de pagamento.

### Risco oculto
Cruzar GR, jurídico, DP, farmacêutico, fiscal, qualidade, manutenção, documentação e processos.

### Estrutura versus resultado
Encontrar crescimento de pessoas, ativos, terceiros ou sistemas sem crescimento proporcional de resultado/produtividade.

## 5. Definições
- Objetivo: resultado que se pretende alcançar.
- Métrica: variável mensurável relacionada ao objetivo.
- KPI: indicador-chave que demonstra se o objetivo está sendo alcançado.
- Estratégia: ações escolhidas para atingir o objetivo.
Nunca misturar os quatro.

## 6. Regra de prontidão para decisão
Uma recomendação só pode ser marcada `READY_FOR_DECISION` se responder:
1. O problema é real?
2. É material?
3. Onde está concentrado?
4. Qual é a causa provável?
5. Quais hipóteses alternativas foram testadas?
6. Quais dados sustentam a conclusão?
7. O que permanece incerto?
8. Qual a consequência de agir e de não agir?
9. Qual alternativa tem melhor impacto/esforço/risco/prazo?
10. Quem executará e como o resultado será comprovado?
11. Estamos eliminando a causa ou adicionando estrutura para compensar um processo ruim?

## 7. Saída executiva
O usuário não deve precisar interpretar a análise.
A resposta final deve ser curta, objetiva, rastreável e acionável.
O detalhe técnico deve ficar disponível sob demanda.

## 8. Métricas do próprio produto
- valor recuperado;
- perdas evitadas;
- tempo entre desvio e decisão;
- percentual de recomendações executadas;
- acurácia do impacto previsto versus realizado;
- percentual de causas confirmadas;
- reincidência após correção;
- tempo para causa raiz;
- percentual de alertas realmente materiais;
- economia por recomendação;
- EBITDA/margem/caixa impactados;
- horas de análise gerencial evitadas.
