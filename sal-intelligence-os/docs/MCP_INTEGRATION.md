# Integração MCP

## Objetivo
Expor dados e ações internas ao Claude por ferramentas MCP com contratos pequenos, auditáveis e orientados a domínio.

## Estratégia
Preferir ferramentas semânticas a SQL livre irrestrito.

Bom:
- `ops.route_performance(branch, period)`
- `finance.dre_variance(period, dimension)`
- `hr.turnover_by_manager(period)`
- `costs.customer_cost_to_serve(customer, period)`

Evitar, por padrão:
- `run_any_sql(query)`

## Servidores sugeridos
- sal-finance
- sal-operations
- sal-commercial
- sal-people
- sal-risk-quality
- sal-legal-tax
- sal-documents
- sal-actions

## Regras
- read-only por padrão;
- qualquer write exige escopo explícito;
- ações sensíveis exigem aprovação humana;
- logar chamada, parâmetros, usuário/agente e resposta resumida;
- nunca expor segredos no prompt;
- limitar retorno a dados necessários;
- mascarar dados pessoais quando possível.

## Arquivo local
Use `.mcp.json` apenas após conhecer URLs/comandos reais.
O arquivo `config/mcp.example.json` é um molde e não contém credenciais.
