# `projects/` — Contexto por projeto (FASE 5)

Cada subpasta aqui é um projeto que o Orchestrator sabe carregar contexto para, via `resolveContext()` (`src/orchestrator/contextResolver.ts`). Quando uma requisição chega com `"project": "<nome>"`, **só** os 5 arquivos abaixo dessa pasta são lidos — nunca o repositório inteiro, nunca outra pasta de projeto.

## Como adicionar um projeto novo

1. Copie `_template/` para `<nome-do-projeto>/` (nome restrito a letras, números, `-` e `_` — é validado por `resolveContext()` contra path traversal).
2. Preencha os arquivos que fizerem sentido para o projeto. Nenhum é obrigatório — o Context Resolver reporta os que faltam em `missing[]` sem erro, e a ausência de um arquivo não bloqueia a orquestração.
3. Não duplique informação que já existe em outro lugar (registries do Control Plane, `C:\SAL_AI_OS\01_INVENTARIO\`, READMEs de projeto) — referencie, não copie.

## Os 5 arquivos

| Arquivo | Para que serve |
|---|---|
| `PROJECT-CONTEXT.md` | O que é o projeto, para quem, por que existe. Visão geral rápida. |
| `DATA-DICTIONARY.md` | Tabelas/campos relevantes (ex.: quais tabelas Supabase, o que cada uma significa) — sem duplicar o schema inteiro, só o que uma IA precisa saber para não interpretar dado errado. |
| `BUSINESS-RULES.md` | Regras de negócio que não estão óbvias só olhando o código/dado (ex.: "regime tributário X só se aplica a filiais Y"). |
| `ARCHITECTURE.md` | Onde o código/dado desse projeto vive de fato (repo, Supabase, Lovable, automação local) — o "onde está a verdade" desse projeto específico. |
| `AI-INSTRUCTIONS.md` | Regras específicas para qualquer IA que for atuar nesse projeto (ex.: "nunca alterar X sem aprovação", convenções próprias). |

## Projetos existentes

Nenhum ainda — `_template/` é só o esqueleto. Populário reais deve vir de quem conhece o projeto de verdade (não inventar regra de negócio a partir de suposição).
