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

## Status atual: FASE 1 (CORE) implementada

O que existe hoje é o núcleo de decisão do orchestrator — classifica a tarefa, resolve contexto, decide roteamento, monta o plano de execução (um agente ou cadeia multi-agente), e aplica os modos de segurança/custo. **Nenhum provider real (OpenAI/Manus/Anthropic/Gemini) está implementado ainda** — isso é a FASE 2, próxima etapa, pendente de decisão sobre chaves de API e SDKs.

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

- **FASE 2** — providers reais (OpenAI, Manus, Anthropic, Gemini) implementando `AIProvider`
- **FASE 5** — pasta `projects/<project>/` populada de verdade (o Context Resolver já sabe ler, mas nenhum projeto foi criado)
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
