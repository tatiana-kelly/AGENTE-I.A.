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

## Status atual: core + persistência + API + padrão de projetos/MCP implementados

O orchestrator classifica a tarefa e seu efeito (`READ`/`WRITE`/`EXTERNAL_ACTION`/`UNKNOWN`), resolve contexto, decide roteamento, monta e encadeia o plano multi-agente, aplica segurança e reserva de custo **antes** da chamada, executa fallback controlado, valida sem autorrevisão e registra tarefas, runs e evidências inclusive para bloqueios/erros. `UNKNOWN`, custo sem teto configurado e pedido de aprovação de provider falham fechados.

**Testes locais:** 60 testes em 8 arquivos, além de `typecheck` e `build`. Continuam sendo testes locais/mockados; não substituem certificação real dos providers, aplicação das migrations nem validação com n8n/Cowork/Claude Code/Codex.

**Único provider ativo hoje: Anthropic** (única chave de IA encontrada no ecossistema local — ver `DISCOVERY-REPORT.md`). OpenAI/Manus/Gemini estão implementados mas sem chave configurada.

⚠️ **Teste real histórico** (`scripts/real-test.mjs`) — chegou à API Anthropic, mas falhou por falta de crédito antes de validar o caminho de sucesso. Ver [REAL-TEST-REPORT.md](REAL-TEST-REPORT.md). Precisa ser repetido após configurar billing e `ANTHROPIC_MAX_COST_PER_CALL_USD`.

⚠️ **Manus**: o adapter foi alinhado em 2026-08-17 ao schema oficial v2 de eventos de `task.listMessages`, incluindo paginação e estado `waiting`. Fixtures no formato legado agora são rejeitados. Ainda é obrigatório um teste contratual real antes de ativá-lo em produção.

⚠️ **Classificação de efeitos ainda é heurística** (FASE 7), mas agora é fail-closed: intenção não reconhecida vira `UNKNOWN` e não chega ao provider. Os casos auditados de falso positivo (`Analise como implementar...`) e falso negativo (`Altere..., remova... e faça deploy`) têm testes de regressão.

**Contexto de projetos**: cada repositório integrado usa `AI-PROJECT.yaml`, `.ai/`, `AGENTS.md`, `CLAUDE.md` e a skill `sal-project`. O registro persiste somente o snapshot autorizado e seu hash; não concede acesso automático ao repositório inteiro.

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
| `src/api/` | API HTTP autenticada e servidor Node para integração com n8n (FASE 13) |
| `src/projects/` | Validador do manifesto, onboarding, snapshot e autorização por projeto |
| `src/mcp/` | MCP stdio somente leitura para clientes locais autorizados |

### O que falta (não implementado ainda)

- **FASE 6** — ampliar o catálogo além da skill inicial `sal-project`
- **FASE 13 (validação externa)** — conectar a API ao n8n real e testar autenticação/continuação ponta a ponta
- **MCP remoto** — adicionar transporte HTTP com autenticação OAuth; o transporte atual é local/stdio
- **FASE 14** — adapter v2 implementado; falta certificação contra chamada real do Manus
- **FASE 19-21** — teste real ponta a ponta em `READ_ONLY`, `docs/` completos

## Como rodar

```bash
npm install
npm run typecheck
npm test
npm run build
npm start
```

## Integrar um projeto

O onboarding cria somente arquivos ausentes e nunca sobrescreve instruções existentes:

```bash
npm run project:init -- C:\github\meu-projeto --id meu-projeto --name "Meu Projeto" --repository empresa/meu-projeto
npm run project:validate -- C:\github\meu-projeto
```

Depois de revisar e preencher o contexto real, sincronize o snapshot no Supabase exclusivo do Orchestrator e conceda somente a capacidade necessária:

```bash
npm run project:sync -- C:\github\meu-projeto
npm run project:grant -- meu-projeto --type agent --principal claude-code --capability read_context
npm run project:grant -- meu-projeto --type agent --principal codex --capability read_context
```

O manifesto nunca contém credenciais. `AGENTS.md` é a instrução compartilhada; `CLAUDE.md` importa `@AGENTS.md` e acrescenta apenas regras específicas do Claude.

## MCP local somente leitura

Configure `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MCP_PRINCIPAL_TYPE` e `MCP_PRINCIPAL_ID` no ambiente seguro do processo e execute:

```bash
npm run build
npm run mcp:start
```

Ferramentas expostas: `projects_list`, `projects_get_context` e `tasks_get`. Todas filtram por `ai_project_permissions`; projeto não autorizado é omitido sem confirmar sua existência. O processo MCP possui a chave de backend, mas ela não é devolvida ao agente. Para Cowork remoto/serviços compartilhados, não exponha stdio nem uma chave estática: aguarde o transporte HTTP com OAuth.

## Modos de execução (FASE 7)

Default é sempre `READ_ONLY` com `DRY_RUN=true` — ver `.env.example`. Só `READ` explícito passa nesse modo; `UNKNOWN` bloqueia. Provider capaz de efeitos externos é reavaliado como `EXTERNAL_ACTION`. Cada provider real também precisa declarar `*_MAX_COST_PER_CALL_USD`; sem teto, a chamada é bloqueada antes de gerar custo.

## Persistência Supabase (FASE 11)

As migrations locais estão em `supabase/migrations/`. Elas criam `ai_tasks`, `ai_runs`, `ai_evidence`, `ai_projects` e `ai_project_permissions`, com chaves estrangeiras, checks, índices, continuidade auditável e RLS. `anon` e `authenticated` não recebem acesso direto; o adapter foi desenhado para o backend com `service_role`.

Quando `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` estiverem configuradas juntas, `orchestrate()` ativa automaticamente o `SupabaseOrchestrationRepository`. Sem ambas, o fluxo continua sem persistência remota; para testes, injete `InMemoryOrchestrationRepository`. Configuração parcial falha antes de chamar qualquer IA.

As três migrations foram aplicadas em 17/08/2026 ao projeto Supabase exclusivo `sal-ai-orchestrator`. O teste contratual remoto confirmou escrita e leitura via `service_role`, bloqueio do acesso `anon` com HTTP 401 e remoção do registro temporário de validação. URL e chaves continuam obrigatoriamente fora do repositório e devem ser fornecidas pelas variáveis de ambiente acima.

## API HTTP (FASE 13)

Todos os endpoints exigem `Authorization: Bearer <N8N_WEBHOOK_SECRET>`; o segredo precisa ter ao menos 32 caracteres. O modo de execução vem exclusivamente do ambiente do servidor e não pode ser alterado pelo payload.

- `POST /orchestrate` — recebe `{ "task": "...", "project": "opcional" }`.
- `GET /tasks/:id` — retorna tarefa, runs e evidências persistidas.
- `POST /tasks/:id/continue` — recebe `{ "approved": true, "approvedMaxCostUsd": 0.50 }` para uma tarefa em `awaiting_approval`.

A continuação usa claim atômico para impedir replay, cria uma nova tarefa ligada à original e registra origem, horário e limite de custo aprovado. Aprovar a ação não permite exceder esse valor nem o teto global da tarefa. O servidor de produção falha ao iniciar sem Supabase e sem `N8N_WEBHOOK_SECRET`.

### Deploy na Vercel

O entrypoint serverless está em `api/index.ts`; `vercel.json` preserva os endpoints públicos acima e limita cada invocação a 300 segundos. Antes do primeiro deploy, configure como segredos da Vercel:

- `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY`;
- `N8N_WEBHOOK_SECRET`, com pelo menos 32 caracteres;
- ao menos uma chave de provider e seu respectivo `*_MAX_COST_PER_CALL_USD`;
- `ORCHESTRATOR_MODE=READ_ONLY` e `DRY_RUN=true` no primeiro rollout.

Valide as duas formas de execução com `npm run typecheck`, `npm run typecheck:vercel`, `npm test` e `npm run build`. Segredos não pertencem ao Git nem a arquivos de deploy.

## Reaproveitamento conhecido (não redesenhar do zero)

- **Persistência do Orchestrator**: é independente do `pendency-tracker`. Não acessar nem alterar aquele projeto; a FASE 11 deve criar somente as tabelas próprias deste repositório.
- **Gating de execução**: `C:\ssw-relatorios\.claude\hooks\pre_tool_check.ps1` — único exemplo real (não só documentado) de whitelist/blacklist de ação, inspirou `securityLayer.ts`.
- **Email**: qualquer notificação/alerta deve sair pelo Email Agent oficial (`ia.sal@salexpress.com.br`), nunca reimplementar envio.

## Convenção de nome de pasta local

O repositório no GitHub se chama `AGENTE-I.A.` (com ponto final). O Windows não aceita pasta local terminada em ponto — use `AGENTE-I.A` (sem o ponto) ao clonar localmente.
