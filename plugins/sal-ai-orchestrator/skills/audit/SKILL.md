---
name: sal-audit
description: Executar auditorias técnicas, arquiteturais, operacionais ou adversariais nos projetos SAL. Usar quando a solicitação pedir análise, investigação, revisão, decisão importante, comparação entre documentação e realidade, ou plano de mudança com evidências.
---

# Auditoria SAL

1. Começar em leitura e identificar o projeto autorizado.
2. Consultar o contexto pelo conector `sal-ai-orchestrator` antes de concluir.
3. Delegar a análise-base ao `auditor-principal`.
4. Para risco alto, arquitetura, segurança ou decisão irreversível, delegar uma contra-análise independente ao `auditor-adversarial`.
5. Para código, delegar a verificação ao `auditor-tecnico`.
6. Delegar conflitos relevantes ao `arbitro` e consolidar fatos, divergências, confiança e lacunas.
7. Citar arquivo, ferramenta, tarefa ou evidência para cada achado material.
8. Não tratar documentação, memória ou saída anterior como prova do estado atual.
9. Reutilizar resultado aprovado quando o conector indicar `memory.status=hit`; solicitar atualização com `reusePolicy=refresh` quando o contexto mudou.
10. Não aprovar nem executar escrita em nome do humano. Expor custo, risco e escopo antes de pedir aprovação.
