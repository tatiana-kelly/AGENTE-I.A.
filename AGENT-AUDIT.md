# AGENT-AUDIT.md — Auditoria Staff/Principal do AGENTE-I.A. (AI Orchestrator, PRP-003)

**Data:** 2026-08-17
**Baseline auditado:** commit `a6e1440`, branch `main`, sincronizado com `origin/main`
**Estado de qualidade no momento da auditoria:** `tsc --noEmit` ✅ · `tsc -p tsconfig.json` (build) ✅ · `vitest run` ✅ 27/27 em 4 arquivos
**Método:** leitura integral do código (`src/` ~1.300 linhas TS, `tests/`, `scripts/`, `projects/`, `.env.example`, `.gitignore`), documentação (README, CLAUDE.md, DISCOVERY-REPORT, REAL-TEST-REPORT), histórico git (varredura de segredos) e confronto documentação × implementação. Nada foi alterado nesta fase.

---

## 1. Arquitetura atual

```
orchestrate(request)                                src/orchestrator/index.ts
  ├─ resolveContext()      FASE 5   carrega projects/<p>/*.md (5 arquivos canônicos)
  ├─ classifyTask()        FASE 1   11 regras regex determinísticas → skills + 4 flags
  ├─ routeTask()           FASE 3   matriz fixa: flags > skill-vote → primary/reviewer/fallback
  ├─ planTask()            FASE 4   3 cadeias MULTI_AGENT codificadas + fallback ONE_AGENT
  ├─ evaluateExecution()   FASE 7   READ_ONLY/ASSISTED/AUTONOMOUS + DRY_RUN (default seguro)
  ├─ ProviderManager.call  FASE 2   registry → 4 providers (openai/anthropic/gemini/manus)
  ├─ validateResult()      FASE 9   1 passada de revisão (X→OPENAI), sem loop de correção
  ├─ buildEvidenceRecord   FASE 8   sink plugável, hoje só InMemoryEvidenceSink
  ├─ CostController        FASE 16  avalia custo… que nenhum provider reporta (sempre unknown)
  └─ Observability         FASE 17  log JSON estruturado no console, métricas "unknown" nunca inventadas
```

Decisões arquiteturais **corretas e que devem ser preservadas** (ver seção 10):
provider abstraction limpa (`AIProvider`), classificador determinístico auditável (sem LLM no caminho de decisão), default de segurança `READ_ONLY+DRY_RUN=true` mesmo com env malformada, evidence sem chain-of-thought, proteção de path traversal no contextResolver, providers registrados só se a chave existir (nunca quebram o startup), zero dependência de SDK (só `zod` em runtime — `fetch` nativo).

**Fato estrutural relevante:** o repositório contém **dois cérebros de orquestração**. O TS da raiz (este auditado) e um segundo, em Python, dentro do subtree `sal-intelligence-os/backend/app/services/` (`orchestrator.py`, `claude_client.py`, `agent_loader.py`, `priority_engine.py`, `data_quality_gate.py`, `audit_trail.py`) — que já rodou um caso real ponta a ponta com LLM (caso DRE, commit `a6e1440`). Eles não se conhecem, não compartilham código e resolvem problemas sobrepostos (chamada Claude, evidence/audit, orquestração de agentes). Não é bug — é decisão da Tatiana manter o subtree — mas é o principal risco de divergência de longo prazo (ver seção 6, R7).

## 2. Componentes existentes (IMPLEMENTADO — funciona e tem teste ou validação real)

| Componente | Arquivo | Evidência |
|---|---|---|
| Classificador determinístico (11 regras) | `taskClassifier.ts` | testes em `routing.test.ts` |
| Matriz de roteamento + reviewer + fallback declarado | `routingEngine.ts` | testes cobrem exemplos da FASE 18 do PRP |
| Planner ONE_AGENT/MULTI_AGENT (3 cadeias) | `taskPlanner.ts` | testado |
| Gate de segurança 3 modos + DRY_RUN | `securityLayer.ts` | testado; default seguro verificado |
| Provider Manager (registry) | `providerManager.ts` | testado |
| 4 providers com `analyze()` + `healthCheck()` | `providers/*.ts` | health real validado: OpenAI ~820ms, Gemini ~1156ms, Manus ~600ms; Anthropic chave válida (crédito desbloqueado em 15/08) |
| Pipeline completo com tratamento de erro estruturado | `index.ts` | REAL-TEST-REPORT: erro HTTP 400 real capturado sem crash |
| Evidence record + sink plugável | `evidenceManager.ts` | testado (in-memory) |
| Context resolver com validação de nome de projeto | `contextResolver.ts` | testado com fixtures |
| Observability estruturada | `observability.ts` | usada em todo o pipeline |
| Higiene de segredos | `.gitignore`, histórico git | `.env` **nunca** commitado (verificado com `git log --all --full-history`); zero chaves hardcoded (grep por `sk-`/`AIza`/JWT) |

## 3. Componentes incompletos (PARCIAL — existe, mas não cumpre o que promete)

| # | Componente | O que falta — com evidência de código |
|---|---|---|
| PA-1 | **Context Engine** | `resolveContext()` carrega os 5 arquivos do projeto, MAS o conteúdo **nunca chega ao provider**: `index.ts:88-93` chama `providerManager.call` só com `prompt: request.task`; o campo `TaskInput.context` existe e nunca é populado. O contexto hoje é decorativo — aparece no resultado, não influencia a resposta da IA. |
| PA-2 | **Fallback** | `RoutingDecision.fallback` é definido em todas as rotas (`routingEngine.ts`), MAS `orchestrate()` nunca o consome — um step com `status: "error"` simplesmente segue para o próximo step do plano. Fallback é promessa de tipo, não comportamento. |
| PA-3 | **Cost Engine** | `costController.evaluate(undefined)` — literal em `index.ts:99`. Nenhum provider extrai `usage` da resposta (grep vazio em `providers/*.ts`), então o custo é sempre `"unknown"` e o resultado da avaliação nunca bloqueia nada. `MAX_COST_PER_TASK_USD` no `.env` não tem efeito real. |
| PA-4 | **Validation/Review Engine** | 1 passada única; o output do reviewer é anexado ao resultado mas **não gera correção nem reprovação** — não existe loop FAIL→CORRECTION→REVIEW nem limite de tentativas. |
| PA-5 | **Confidence** | valores fixos por regra de rota (0.9/0.85/0.8/0.6) — heurística honesta e documentada, mas sem os "reasons" estruturados que o alvo pede (fontes, testes, concordância entre agentes). |
| PA-6 | **Provider Anthropic (TS)** | `max_tokens` default 4096 **sem detecção de truncamento** (`stop_reason` não é lido). Esta é exatamente a classe de bug já encontrada e corrigida no lado Python (`sal-intelligence-os`, commit `a6e1440`) — a correção não foi portada para o TS. Latente, vai morder quando a resposta for longa. |
| PA-7 | **Provider Manus** | `task.listMessages` com schema de resposta **não confirmado contra chamada real** (limitação já documentada no próprio código — correto — mas segue aberta). |
| PA-8 | **Heurística de escrita** | `isWriteAction = classification.requiresImplementation` (`index.ts:53`) — sinal por palavra-chave; "corrija a análise do relatório" seria tratado como escrita, e um provider com side-effects reais (Manus agindo sobre ferramentas) não é detectado pelo prompt. Limitação documentada, não resolvida. |
| PA-9 | **projects/** | só `_template/` existe; nenhum projeto real populado (decisão correta — não inventar regra de negócio — mas significa que a FASE 5 nunca foi exercitada com conteúdo real). |
| PA-10 | **task_id** | `${Date.now()}-${provider}` — colisão possível em steps paralelos futuros; sem ULID/UUID. |

## 4. Componentes ausentes (AUSENTE — documentado/planejado, zero código)

| # | Item | Referência |
|---|---|---|
| AU-1 | **FASE 6 — Skill Engine**: `skills/` com SKILL.md/ROUTING.md/VALIDATION.md; hoje "skill" é só um union type de 10 strings | README "O que falta" |
| AU-2 | **FASE 11 — Persistência Supabase** (`ai_tasks`/`ai_runs`/`ai_evidence`, migrations); env vars já previstas no `.env.example`, zero código | README; prior art mapeado no `pendency-tracker` |
| AU-3 | **FASE 13 — API HTTP** (`POST /orchestrate`, `GET /tasks/:id`, `POST /tasks/:id/continue`) + integração n8n; `N8N_WEBHOOK_SECRET` previsto, sem servidor HTTP algum no repo | README |
| AU-4 | **Human-in-the-loop real**: `requiresApproval` é calculado e retornado, mas não existe workflow APPROVE/REJECT/MODIFY — sem persistência (AU-2) não há onde uma aprovação "viver" entre requisições | Missão §12 |
| AU-5 | **Risk Engine** como classificação LOW/MEDIUM/HIGH/CRITICAL — hoje o risco é binário (é escrita? sim/não) | Missão §11 |
| AU-6 | **Intent Engine estruturado** (READ/ANALYZE/PLAN/CREATE/MODIFY/EXECUTE/…) — as 4 flags atuais são um subconjunto | Missão §3 |
| AU-7 | **Matriz de capacidades configurável** — `SKILL_DEFAULT_PROVIDER` e cadeias do planner são hardcoded; missão pede configurável (inclui categoria LONG_HORIZON_AGENT/Fable, que não existe: `ProviderName` é union fechado de 4) | Missão §5-6 |
| AU-8 | **Retry/backoff/timeout por step, paralelização, dependências** — `httpClient` tem timeout, mas sem retry em 429/5xx; steps são estritamente sequenciais | Missão §7 |
| AU-9 | **docs/** (architecture.md, routing.md, providers.md, security.md…) — prometido na seção 8 do DISCOVERY, nunca criado | DISCOVERY §8 |
| AU-10 | **Lint** — não há ESLint/Biome configurado; `npm run lint` não existe (missão §20 exige lint no gate de qualidade) | `package.json` |
| AU-11 | **FASE 19-21 completas** — o teste real rodou e validou o pipeline, mas falhou na chamada por falta de crédito (já resolvido em 15/08); não foi re-executado ponta a ponta com resposta real no lado TS | REAL-TEST-REPORT |

## 5. Dívida técnica

1. **Contexto morto no pipeline** (PA-1) — a mais séria: cria a ilusão de que o projeto influencia a resposta.
2. **Duplicação latente entre os dois orchestrators** (TS × Python) — chamada Claude, evidence, audit e orquestração implementados 2×, com o fix de truncamento aplicado só de um lado.
3. **Interfaces que prometem mais do que o runtime entrega** (fallback, cost, TaskInput.context) — o tipo diz uma coisa, a execução outra; isso corrói a confiança de quem lê os tipos como contrato.
4. **Sem captura de `usage`** nas respostas (OpenAI/Anthropic/Gemini todas reportam tokens; nada é lido) — bloqueia Cost Engine e Observability de custo de verdade.
5. **Ausência de lint** — convive-se sem, mas o gate de qualidade da missão (§20) fica incompleto.
6. Review prompt embute o output do primário sem delimitação/sanitização (superfície de prompt injection entre agentes — moderada hoje, cresce quando Manus executar ferramentas de verdade).

## 6. Riscos

| # | Risco | Gravidade | Mitigação |
|---|---|---|---|
| R1 | Decisões tomadas achando que o contexto do projeto foi considerado (PA-1) | **ALTA** | P0-1 |
| R2 | Truncamento silencioso de resposta longa no provider TS Anthropic (PA-6) | **ALTA** | P0-2 (portar fix do Python) |
| R3 | Custo real de IA sem nenhum controle efetivo (PA-3) — a conta chega sem aviso | ALTA | P0-3 |
| R4 | Fallback anunciado nos tipos que não existe em runtime (PA-2) — falsa resiliência | MÉDIA-ALTA | P0-4 |
| R5 | Falso positivo/negativo do classificador por palavra-chave gating escrita (PA-8) | MÉDIA | P1 (Risk Engine) + P2 (Intent v2); nunca substituir por LLM puro — camada determinística continua sendo o piso auditável |
| R6 | `task.listMessages` do Manus com schema não confirmado (PA-7) | MÉDIA | P1, 1 chamada real de validação |
| R7 | Divergência TS × Python (dois orchestrators no mesmo repo) | MÉDIA (cresce com o tempo) | Decisão de governança (Tatiana): definir qual é o runtime canônico de orquestração e qual é aplicação-cliente; não resolver unilateralmente (CLAUDE.md) |
| R8 | Prompt injection entre agentes via review prompt (dívida 6) | MÉDIA-BAIXA hoje | P1 junto com retry/loop de correção |
| R9 | n8n ainda não localizado — FASE 13 não validável ponta a ponta | BAIXA (já registrado no DISCOVERY) | manter como dependência externa aberta |

**Segurança (auditoria específica da missão §18):** `.env` nunca commitado no histórico ✅ · zero segredos hardcoded ✅ · `.gitignore` correto ✅ · path traversal bloqueado no contextResolver ✅ · default READ_ONLY+DRY_RUN ✅ · sem autenticação/autorização (não se aplica ainda — não há API HTTP; vira requisito duro do P1-2) · logs não vazam segredo (Observability loga status/latência/erro, nunca payload de credencial) ✅.

## 7. Fases recomendadas (ROADMAP P0/P1/P2/P3)

**P0 — Corrigir o que já existe antes de adicionar qualquer coisa (1 ciclo curto):**
1. Injetar o contexto resolvido no prompt dos providers (fecha PA-1/R1). Formato: blocos delimitados por arquivo, com aviso explícito de fonte.
2. Detecção de truncamento no provider TS Anthropic — ler `stop_reason`, erro claro em vez de resposta cortada (porta do fix `a6e1440`).
3. Capturar `usage` (tokens) nas respostas dos 3 providers que reportam + calcular custo estimado por tabela de preço configurável + **ligar de verdade** o CostController ao gate (bloquear acima de `MAX_COST_PER_TASK_USD`).
4. Implementar o fallback em runtime: step falhou → tentar `routing.fallback` uma vez, registrando `fallback_triggered/fallback_reason` no evidence (os campos já existem no schema e nunca são usados).
5. Adicionar ESLint + script `lint` ao gate de qualidade.
6. task_id com UUID (`crypto.randomUUID()`).

**P1 — Fundação de plataforma (persistência + API + aprovação humana):**
1. FASE 11: Supabase `ai_tasks`/`ai_task_steps`/`ai_runs`/`ai_evidence`/`ai_approvals` via migrations, reaproveitando o padrão do `pendency-tracker` (`platform_action` vs. ação real aprovada) — decisão já registrada no DISCOVERY, não redesenhar.
2. FASE 13: API HTTP mínima (`POST /orchestrate`, `GET /tasks/:id`, `POST /tasks/:id/approve|reject|continue`, `GET /tasks/:id/evidence`) com autenticação (mínimo: bearer secret; o `N8N_WEBHOOK_SECRET` já está previsto).
3. Human-in-the-loop real em cima de 1+2: plano persiste `pending_approval`, execução só continua após `approve` — hoje o `requiresApproval` morre na resposta.
4. Risk Engine: LOW/MEDIUM/HIGH/CRITICAL derivado de sinais (escrita, alvo do side-effect, reversibilidade); HIGH/CRITICAL ⇒ aprovação obrigatória independente do modo.
5. Retry/backoff (429/5xx) no httpClient + loop de correção na validação com `MAX_REVIEW_ATTEMPTS` (default 2).
6. Validar `task.listMessages` do Manus com 1 chamada real e fixar o schema.

**P2 — Inteligência de orquestração:**
1. Skill Engine (AU-1): `skills/<nome>/SKILL.md` + metadados estruturados (entradas, saídas, risco, agentes recomendados, critérios de validação), registry carregável — as regras regex viram o *bootstrap* da detecção, não o teto.
2. Intent Engine v2 (AU-6): taxonomia READ/ANALYZE/PLAN/CREATE/MODIFY/EXECUTE/INVESTIGATE/REVIEW/DECIDE; camada determinística primeiro, classificação semântica (LLM barato) só como desempate registrado em evidence — nunca decisão inteira via LLM sem trilha.
3. Matriz de capacidades configurável (YAML/JSON) substituindo `SKILL_DEFAULT_PROVIDER` hardcoded; inclui a categoria `LONG_HORIZON_AGENT` (Fable) — exige abrir o union `ProviderName` para extensível.
4. Confidence Engine com `reasons[]` estruturados (fontes, revisão, testes, consistência).
5. Cost policies (`LOW_COST`/`BALANCED`/`QUALITY_FIRST`) usando o custo real medido no P0-3.

**P3 — Escala e maturidade:**
paralelização de steps com dependências; timeout por step; docs/ completos (AU-9); dashboards de observabilidade; E2E com cenários reais dos dois exemplos do critério de sucesso da missão; avaliação de deploy (Vercel functions × runtime dedicado — a API do P1 é long-running com polling do Manus de até 5min, o que **não cabe** em serverless padrão da Vercel; decisão consciente necessária, não default).

## 8. Dependências

- **P1 inteiro depende de**: projeto Supabase escolhido (novo × reuso do `pendency-tracker` — decisão de governança), e de onde a API vai rodar (ver P3/Vercel acima).
- **FASE 13 validação ponta a ponta depende de**: localizar o n8n (gap aberto desde o DISCOVERY).
- **Fable como agente depende de**: chave/conta e da abertura do union `ProviderName` (P2-3).
- **Caso real de sucesso depende de**: crédito Anthropic ativo (✅ desde 15/08) e re-execução do `real-test.mjs`.
- **R7 (dois orchestrators) depende de**: decisão da Tatiana sobre runtime canônico — bloqueia consolidação, não bloqueia P0/P1.

## 9. Melhorias prioritárias (resumo executivo)

> **P0 é pequeno e barato — ~6 itens cirúrgicos que fazem o sistema existente dizer a verdade sobre si mesmo** (contexto que chega, fallback que existe, custo que é medido, resposta que não trunca em silêncio). Nada de feature nova antes disso.
> Depois, P1 transforma biblioteca em plataforma (persistência + API + aprovação humana real) — é onde o `requiresApproval` deixa de ser um boolean decorativo.

## 10. O que NÃO deve ser alterado

1. **A divisão de responsabilidades entre IAs** (CLAUDE.md "NÃO ALTERAR") — n8n executa, Orchestrator roteia, ChatGPT decide, Manus investiga, Claude constrói, Gemini = Google. Qualquer mudança volta para a Tatiana.
2. **Defaults de segurança** — `READ_ONLY` + `DRY_RUN=true` mesmo com env malformada, e a regra de push com autorização explícita a cada vez.
3. **Classificador determinístico como piso** — pode ganhar camadas por cima (Intent v2), nunca ser substituído por classificação LLM opaca; a auditabilidade do roteamento é feature, não limitação.
4. **Abstração `AIProvider` e o Provider Manager** — corretos; estender, não reescrever.
5. **Evidence sem chain-of-thought** — princípio FASE 8, mantém-se.
6. **`sal-intelligence-os/` como subtree** — decisão registrada da Tatiana; não mover, não fundir, não "limpar" sem decisão explícita.
7. **Filosofia de dependência mínima** (fetch nativo, sem SDKs) — só abandonar com justificativa concreta por provider.
8. **Testes de routing como contrato** (CLAUDE.md) — mudanças na matriz mantêm os testes passando ou os atualizam deliberadamente.

---

*Auditoria concluída sem nenhuma alteração de código. Próximo passo: validação deste diagnóstico e do roadmap pela Tatiana; implementação começa pelo P0 somente após aprovação.*
