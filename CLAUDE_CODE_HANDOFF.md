# PROMPT PARA INICIAR O PROJETO NO CLAUDE CODE

Você recebeu o repositório **SAL Intelligence OS**.

Leia primeiro:
1. `CLAUDE.md`
2. `docs/MASTER_SPEC.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DATA_MODEL.md`
5. `docs/MCP_INTEGRATION.md`
6. `docs/IMPLEMENTATION_BACKLOG.md`
7. `config/priority-scoring.yaml`
8. todos os arquivos em `.claude/rules/`
9. os agentes em `.claude/agents/`

## Objetivo
Construir uma plataforma de inteligência executiva para a SAL Express.
A empresa já possui dados, números, KPIs e dashboards. Não queremos outro dashboard.

Queremos um sistema que:
- detecte desvios;
- prove que o desvio é real;
- encontre onde está concentrado;
- investigue causa;
- confronte hipóteses;
- quantifique impacto;
- acione obrigatoriamente o Agente de Soluções e Ações Práticas quando o diagnóstico estiver suficiente;
- proponha três soluções executáveis;
- recomende a solução com maior resultado e menor esforço;
- direcione exatamente onde agir;
- defina dono, prazo, KPI e meta;
- acompanhe resultado;
- aprenda com intervenções anteriores.

## Regra não negociável
Nenhum alerta pode terminar em "o indicador está ruim" ou "investigar".
O produto de cada alerta é **uma decisão potencial**.

## Implementação
Comece pela Fase 0 + Fase 1 do backlog.
Não tente integrar todos os sistemas de uma vez.
Crie abstrações de conectores e dados mockados realistas para desenvolver o fluxo ponta a ponta.

### Stack preferida
- Python
- FastAPI
- Pydantic
- PostgreSQL
- SQLAlchemy
- pgvector quando houver documentos
- Redis apenas se necessário
- frontend simples orientado a Decision Queue
- testes automatizados

Se houver boa razão técnica para alterar a stack, documente a decisão antes.

## Primeiro incremento funcional
Implemente um caso ponta a ponta:
1. importar dados mockados de DRE + orçamento + operação;
2. detectar um desvio material;
3. gerar Alert;
4. chamar/orquestrar Investigador + especialistas relevantes + Provocador;
5. consolidar Diagnosis;
6. gerar 3 Recommendations;
7. calcular prioridade;
8. acionar o Agente de Soluções e Ações Práticas;
9. comparar 3 alternativas por impacto, esforço, prazo, risco e reversibilidade;
10. colocar em Decision Queue;
11. permitir decisão humana;
12. registrar ActionExecution;
13. simular resultado posterior;
14. registrar OrganizationalLearning.

## Critério de qualidade
Crie testes que falhem se:
- alerta não tiver impacto;
- alerta não tiver concentração;
- recomendação não tiver 3 alternativas;
- recomendação não tiver dono/prazo/KPI;
- status READY_FOR_DECISION ocorrer com baixa confiança;
- decisão sensível não solicitar validação humana;
- o sistema recomendar aumento de estrutura sem registrar teste de capacidade/produtividade/processo.

## Entrega esperada do primeiro ciclo
Antes de programar, apresente:
1. arquitetura final proposta;
2. árvore do repositório;
3. entidades e contratos;
4. fluxo de agentes;
5. plano da Fase 0;
6. plano da Fase 1;
7. riscos e decisões técnicas.

Depois, implemente em incrementos pequenos, executando testes a cada bloco.


## Caso obrigatório de validação
Antes de considerar o MVP concluído, execute o fluxo sobre `examples/dre_margin_case.md`.
O sistema não pode concluir prematuramente que descontos ou mix são causas únicas.
Deve demonstrar investigação, provocação, revisão, solução, priorização e plano de execução.
