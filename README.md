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

## Status atual: core endurecido + FASE 11 implementada localmente; API ainda pendente

O orchestrator classifica a tarefa e seu efeito (`READ`/`WRITE`/`EXTERNAL_ACTION`/`UNKNOWN`), resolve contexto, decide roteamento, monta e encadeia o plano multi-agente, aplica segurança e reserva de custo **antes** da chamada, executa fallback controlado, valida sem autorrevisão e registra tarefas, runs e evidências inclusive para bloqueios/erros. `UNKNOWN`, custo sem teto configurado e pedido de aprovação de provider falham fechados.

**Testes locais:** 49 testes em 5 arquivos, além de `typecheck` e `build`. Continuam sendo testes locais/mockados; não substituem certificação real dos providers nem aplicação da migration em um projeto Supabase.

**Único provider ativo hoje: Anthropic** (única chave de IA encontrada no ecossistema local — ver `DISCOVERY-REPORT.md`). OpenAI/Manus/Gemini estão implementados mas sem chave configurada.

⚠️ **Teste real histórico** (`scripts/real-test.mjs`) — chegou à API Anthropic, mas falhou por falta de crédito antes de validar o caminho de sucesso. Ver [REAL-TEST-REPORT.md](REAL-TEST-REPORT.md). Precisa ser repetido após configurar billing e `ANTHROPIC_MAX_COST_PER_CALL_USD`.

⚠️ **Manus**: o adapter foi alinhado em 2026-08-17 ao schema oficial v2 de eventos de `task.listMessages`, incluindo paginação e estado `waiting`. Fixtures no formato legado agora são rejeitados. Ainda é obrigatório um teste contratual real antes de ativá-lo em produção.

⚠️ **Classificação de efeitos ainda é heurística** (FASE 7), mas agora é fail-closed: intenção não reconhecida vira `UNKNOWN` e não chega ao provider. Os casos auditados de falso positivo (`Analise como implementar...`) e falso negativo (`Altere..., remova... e faça deploy`) têm testes de regressão.

**FASE 5 — Contexto**: `projects/_template/` tem o esqueleto dos 5 arquivos (`PROJECT-CONTEXT.md`, `DATA-DICTIONARY.md`, `BUSINESS-RULES.md`, `ARCHITECTURE.md`, `AI-INSTRUCTIONS.md`) e `projects/README.md` documenta a convenção. Nenhum projeto real foi populado ainda — fazer isso exige conhecimento de negócio real, não deve ser inventado.

### Módulos (`src/orchestrator/`)

| Módulo | Responsabilidade |
|---|---|
| `taskClassifier.ts` | Classifica skills, sinais de roteamento e nível de efeito; `UNKNOWN` é fail-closed |
| `contextResolver.ts` | Carrega só o contexto do projeto pedido (`projects/<project>/*.md`), nunca o repo inteiro |
| `routingEngine.ts` | Matriz de roteamento (FASE 3) — decide provider primário, reviewer e fallback |
| `taskPlanner.ts` | Decide `ONE_AGENT` vs `MULTI_AGENT` e a ordem da cadeia (FASE 4) |
| `providerManager.ts` | Registro de providers (`AIProvider`) — o Router nunca importa um provider concreto direto |
| `validationEngine.ts` | Retorna `APPROVED`/`REJECTED`/`NEEDS_HUMAN` e bloqueia autorrevisão |
| `evidenceManager.ts` | Registra sucesso, bloqueio, skip, erro e fallback |
| `costController.ts` | Reserva teto acumulado antes de cada chamada; custo desconhecido bloqueia |
| `securityLayer.ts` | Modos `READ_ONLY`/`ASSISTED`/`AUTONOMOUS` + `DRY_RUN` (FASE 7) |
| `observability.ts` | Log estruturado; métrica indisponível vira `"unknown"`, nunca é inventada (FASE 17) |
| `index.ts` | `orchestrate()` — amarra tudo acima |
| `src/persistence/` | Contrato, repositório em memória e adapter REST do Supabase (FASE 11) |

### O que falta (não implementado ainda)

- **FASE 6** — `skills/` com `SKILL.md`/`ROUTING.md`/`VALIDATION.md`
- **FASE 13** — API HTTP (`POST /orchestrate`, `GET /tasks/:id`, `POST /tasks/:id/continue`) e integração com n8n
- **FASE 14** — adapter v2 implementado; falta certificação contra chamada real do Manus
- **FASE 19-21** — teste real ponta a ponta em `READ_ONLY`, `docs/` completos

## Como rodar

```bash
npm install
npm run typecheck
npm test
npm run build
```

## Modos de execução (FASE 7)

Default é sempre `READ_ONLY` com `DRY_RUN=true` — ver `.env.example`. Só `READ` explícito passa nesse modo; `UNKNOWN` bloqueia. Provider capaz de efeitos externos é reavaliado como `EXTERNAL_ACTION`. Cada provider real também precisa declarar `*_MAX_COST_PER_CALL_USD`; sem teto, a chamada é bloqueada antes de gerar custo.

## Persistência Supabase (FASE 11)

A migration local está em `supabase/migrations/202608170001_create_orchestrator_persistence.sql`. Ela cria somente `ai_tasks`, `ai_runs` e `ai_evidence`, com chaves estrangeiras, checks, índices e RLS. `anon` e `authenticated` não recebem acesso direto; o adapter foi desenhado para o backend com `service_role`.

Quando `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` estiverem configuradas juntas, `orchestrate()` ativa automaticamente o `SupabaseOrchestrationRepository`. Sem ambas, o fluxo continua sem persistência remota; para testes, injete `InMemoryOrchestrationRepository`. Configuração parcial falha antes de chamar qualquer IA.

Esta branch apenas cria a migration: ela **não foi aplicada a nenhum Supabase remoto**. Aplicar a migration e executar um teste contratual real exigem autorização e ambiente do projeto correto.

## Reaproveitamento conhecido (não redesenhar do zero)

- **Persistência do Orchestrator**: é independente do `pendency-tracker`. Não acessar nem alterar aquele projeto; a FASE 11 deve criar somente as tabelas próprias deste repositório.
- **Gating de execução**: `C:\ssw-relatorios\.claude\hooks\pre_tool_check.ps1` — único exemplo real (não só documentado) de whitelist/blacklist de ação, inspirou `securityLayer.ts`.
- **Email**: qualquer notificação/alerta deve sair pelo Email Agent oficial (`ia.sal@salexpress.com.br`), nunca reimplementar envio.

## Convenção de nome de pasta local

O repositório no GitHub se chama `AGENTE-I.A.` (com ponto final). O Windows não aceita pasta local terminada em ponto — use `AGENTE-I.A` (sem o ponto) ao clonar localmente.
