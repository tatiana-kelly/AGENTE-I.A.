---
name: sal-project
description: Auditar, compreender e melhorar um projeto integrado ao SAL AI Orchestrator. Usar quando a tarefa mencionar auditoria de projeto, melhoria contínua, contexto do projeto, AI-PROJECT.yaml, registro no Orchestrator ou conformidade das instruções de agentes.
---

# SAL Project

## Fluxo

1. Ler `AI-PROJECT.yaml`, `AGENTS.md` e as instruções específicas do agente antes de agir.
2. Validar o manifesto com o comando do projeto. Se ele não existir, propor o onboarding; não inventar identidade, repositório ou permissões.
3. Restringir leituras a `access.allowed_paths` e nunca acessar `access.denied_paths`.
4. Começar em leitura: levantar evidências, riscos e recomendações sem modificar o projeto.
5. Antes de qualquer mudança, confirmar que o modo e a aprovação permitem a ação. Respeitar separadamente aprovações para push, pull request, deploy e migration.
6. Executar somente os comandos declarados em `commands` para validar mudanças.
7. Entregar achados com arquivo/trecho, impacto, recomendação e limitações. Não registrar raciocínio privado.

## Orchestrator

- Preferir as ferramentas MCP somente leitura `projects_list`, `projects_get_context` e `tasks_get` quando estiverem disponíveis.
- Tratar o contexto devolvido pelo Orchestrator como snapshot; citar `contextSha256` para permitir auditoria.
- Não usar o MCP para contornar permissões locais ou instruções do repositório.
- Preservar os papéis oficiais do SAL AI OS. Claude Code continua sendo o construtor oficial; ampliar esse papel para outro agente exige aprovação estrutural da Tatiana.
