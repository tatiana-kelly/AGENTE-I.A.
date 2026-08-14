# AGENTE-I.A. — SAL AI OS: AI Orchestrator / Multi-Model Router

Camada central de orquestração de IA da SAL Express (PRP-003). Decide automaticamente qual IA usa, quais ferramentas, qual contexto, se precisa de uma ou várias IAs, quem revisa o resultado, quais evidências foram usadas, o nível de confiança e se a ação pode rodar sozinha ou precisa de aprovação.

## Arquitetura (oficial — não alterar)

```
n8n               = QUANDO E COMO EXECUTAR
AI ORCHESTRATOR   = QUAL IA DEVE PENSAR/EXECUTAR   (este repositório)
CHATGPT/OPENAI    = QUAL É A MELHOR DECISÃO
MANUS             = VÁ INVESTIGAR / FAZER
CLAUDE / CLAUDE CODE = CONSTRUA
GEMINI            = TRABALHE NO ECOSSISTEMA GOOGLE
SUPABASE          = ONDE ESTÃO OS DADOS
GITHUB            = ONDE ESTÁ A VERDADE DO CÓDIGO
VERCEL            = DEPLOY
```

Ver [DISCOVERY-REPORT.md](DISCOVERY-REPORT.md) para o levantamento que precedeu a implementação (arquitetura encontrada, prior art reaproveitável, gaps, riscos).

## Status atual: FASE 1 (CORE) + FASE 2 (PROVIDERS) + FASE 5 (CONTEXTO) implementadas

O orchestrator classifica a tarefa, resolve contexto, decide roteamento, monta o plano (um agente ou cadeia multi-agente), aplica o gate de segurança/custo, **chama os providers de verdade** (`ProviderManager`), roda a cadeia de revisão (FASE 9) e registra evidência (FASE 8) — pipeline completo, ponta a ponta. `buildProviderManagerFromEnv()` registra automaticamente só os providers cuja API key existir no `.env`; provider sem chave configurada é pulado (`status: "skipped"`), nunca quebra a execução.

**Único provider ativo hoje: Anthropic** (única chave de IA encontrada no ecossistema local — ver `DISCOVERY-REPORT.md`). OpenAI/Manus/Gemini estão implementados mas sem chave configurada.

⚠️ **Teste real (FASE 19) já rodado** (`scripts/real-test.mjs`) — a pipeline funciona corretamente ponta a ponta, mas a chamada real à Anthropic falhou por **falta de crédito na conta dona da chave atual** (não é bug — ver [REAL-TEST-REPORT.md](REAL-TEST-REPORT.md)). Rodar de novo depois de resolver o crédito.

⚠️ **Manus**: a doc oficial da API v2 foi consultada em 2026-08-13 (`open.manus.im/docs/api-reference/...`) para `task.create` e `task.detail`, confirmados. O endpoint `task.listMessages` usado para buscar o resultado final é citado por nome na doc mas seu schema de resposta não pôde ser confirmado nesta sessão — **validar contra uma chamada real antes de depender disso em produção** (ver comentário em `src/providers/manus.ts`).

⚠️ **Heurística de ação de escrita** (FASE 7): `orchestrate()` usa `classification.requiresImplementation` pra decidir se uma tarefa é "escrita" (exige aprovação fora de AUTONOMOUS). Isso é só um sinal por palavra-chave no prompt — uma tarefa de *análise* de código pode acionar as mesmas palavras-chave de uma tarefa de *implementação* e ser tratada como escrita indevidamente. Documentado como limitação conhecida em `src/orchestrator/index.ts`, não resolvido ainda.

**FASE 5 — Contexto**: `projects/_template/` tem o esqueleto dos 5 arquivos (`PROJECT-CONTEXT.md`, `DATA-DICTIONARY.md`, `BUSINESS-RULES.md`, `ARCHITECTURE.md`, `AI-INSTRUCTIONS.md`) e `projects/README.md` documenta a convenção. Nenhum projeto real foi populado ainda — fazer isso exige conhecimento de negócio real, não deve ser inventado.

### Módulos (`src/orchestrator/`)

| Módulo | Responsabilidade |
|---|---|
| `taskClassifier.ts` | Classifica a tarefa em skills + sinais (investigação, decisão, implementação, Google Workspace) |
| `contextResolver.ts` | Carrega só o contexto do projeto pedido (`projects/<project>/*.md`), nunca o repo inteiro |
| `routingEngine.ts` | Matriz de roteamento (FASE 3) — decide provider primário, reviewer e fallback |
| `taskPlanner.ts` | Decide `ONE_AGENT` vs `MULTI_AGENT` e a ordem da cadeia (FASE 4) |
| `providerManager.ts` | Registro de providers (`AIProvider`) — o Router nunca importa um provider concreto direto |
| `validationEngine.ts` | Roda a cadeia de revisão (MANUS→CHATGPT, CLAUDE→CHATGPT, GEMINI→CHATGPT — FASE 9) |
| `evidenceManager.ts` | Monta o registro de evidência estruturado (FASE 8), sink plugável (hoje só em memória) |
| `costController.ts` | `max_cost_per_task`, `require_confirmation_above` — sem billing complexo (FASE 16) |
| `securityLayer.ts` | Modos `READ_ONLY`/`ASSISTED`/`AUTONOMOUS` + `DRY_RUN` (FASE 7) |
| `observability.ts` | Log estruturado; métrica indisponível vira `"unknown"`, nunca é inventada (FASE 17) |
| `index.ts` | `orchestrate()` — amarra tudo acima |

### O que falta (não implementado ainda)

- **FASE 6** — `skills/` com `SKILL.md`/`ROUTING.md`/`VALIDATION.md`
- **FASE 11** — persistência real em Supabase para `ai_tasks`/`ai_runs`/`ai_evidence` (ver seção "Reaproveitamento" abaixo — não desenhar do zero)
- **FASE 13** — API HTTP (`POST /orchestrate`, `GET /tasks/:id`, `POST /tasks/:id/continue`) e integração com n8n
- **FASE 14** — integração com a API oficial (não deprecated) do Manus
- **FASE 19-21** — teste real ponta a ponta em `READ_ONLY`, `docs/` completos

## Como rodar

```bash
npm install
npm run typecheck
npm test
npm run build
```

## Modos de execução (FASE 7)

Default é sempre `READ_ONLY` com `DRY_RUN=true` — ver `.env.example`. Ações de escrita exigem `ASSISTED` (aprovação explícita) ou `AUTONOMOUS` (autorizado previamente) para rodar de fato.

## Reaproveitamento conhecido (não redesenhar do zero)

- **Evidence/audit schema**: o Supabase `pendency-tracker` já tem `email_learning_rules` (separa ação-na-plataforma de ação-real-aprovada), `integration_action_audit`, `integration_ingestion_audit` — usar como referência de schema real em produção para a FASE 11.
- **Gating de execução**: `C:\ssw-relatorios\.claude\hooks\pre_tool_check.ps1` — único exemplo real (não só documentado) de whitelist/blacklist de ação, inspirou `securityLayer.ts`.
- **Email**: qualquer notificação/alerta deve sair pelo Email Agent oficial (`ia.sal@salexpress.com.br`), nunca reimplementar envio.

## Convenção de nome de pasta local

O repositório no GitHub se chama `AGENTE-I.A.` (com ponto final). O Windows não aceita pasta local terminada em ponto — use `AGENTE-I.A` (sem o ponto) ao clonar localmente.
