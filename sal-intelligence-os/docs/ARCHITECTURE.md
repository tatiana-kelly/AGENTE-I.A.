# Arquitetura proposta

## Componentes
1. **Data Connectors** — ERP/TMS/WMS/CRM/Financeiro/RH/DP/telemetria/documentos.
2. **Canonical Data Layer** — camada padronizada para fatos e dimensões.
3. **Data Quality Gate** — valida atualização, duplicidade, completude, conceito e comparabilidade.
4. **Metric Registry** — fórmulas oficiais, metas, limites, periodicidade, dono e fonte.
5. **Detection Engine** — regras, anomalias, tendência, recorrência, Pareto e materialidade.
6. **Agent Orchestrator** — seleciona e encadeia agentes.
7. **Investigation Engine** — drill-down, decomposição, contrafactual e teste de hipótese.
8. **Priority Engine** — impacto × urgência × confiança × reversibilidade ÷ esforço.
9. **Solutions Engine** — converte diagnóstico validado em 3 alternativas executáveis e plano recomendado.
10. **Decision Queue** — fila executiva de decisões.
11. **Action Tracker** — ação, dono, prazo, meta, evidência, resultado.
12. **Organizational Memory** — histórico de decisão, previsão versus realizado e lições.
13. **Audit Trail** — fonte, timestamp, consulta, versão de regra, agente e decisão humana.

## Claude / MCP
Usar Claude como camada de raciocínio e orquestração.
Usar MCP para disponibilizar ferramentas e fontes internas ao Claude.
Criar servidores MCP por domínio ou um gateway MCP interno com ferramentas claramente nomeadas, por exemplo:
- `finance.query_dre`
- `finance.query_cashflow`
- `costs.query_by_branch`
- `ops.query_shipments`
- `ops.query_route_productivity`
- `warehouse.query_capacity`
- `hr.query_turnover`
- `payroll.query_overtime`
- `legal.query_cases`
- `risk.query_vehicle_events`
- `quality.query_temperature_events`
- `sales.query_customer_margin`
- `claims.query_losses`
- `docs.search_policy`

## Princípio de acesso
Cada agente recebe somente as ferramentas necessárias ao seu domínio.
O coordenador pode chamar agentes, mas não precisa ter acesso direto a todos os dados brutos.

## Persistência sugerida
- PostgreSQL: fatos, dimensões, métricas, alertas, ações, auditoria.
- Object storage: documentos e evidências.
- Vector store/pgvector: busca semântica em documentos.
- Redis: cache, locks, filas curtas.
- Worker queue: análises programadas e reprocessamentos.

## Backend sugerido
Python + FastAPI para APIs e regras analíticas.
Pydantic para contratos.
SQLAlchemy para persistência.
Jobs agendados para detecção.
A arquitetura deve permitir trocar o provedor de LLM sem reescrever regras de negócio.

## Frontend
Tela principal: `Decision Queue`, não dashboard.
Filtros:
- severidade;
- impacto;
- esforço;
- área;
- filial;
- cliente;
- status;
- responsável.

Card de decisão:
- diagnóstico em 5 linhas;
- impacto;
- confiança;
- onde agir;
- recomendação;
- 3 alternativas;
- dono;
- prazo;
- botão aprovar/devolver/solicitar evidência.

## Observabilidade
Registrar:
- prompt/template version;
- agentes acionados;
- ferramentas chamadas;
- fontes consultadas;
- tempo;
- custo;
- confiança;
- decisão humana;
- resultado posterior.
