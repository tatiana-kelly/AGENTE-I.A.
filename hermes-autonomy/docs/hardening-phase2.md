# Fase 2 — Hardening e governança antes da integração

Data: 18/09/2026 · Sem integração, sem IA, sem casos reais, sem 24/7, sem deploy, sem push.
Todas as consultas ao Supabase foram de **metadados, somente leitura**, e o valor do segredo **nunca** foi exibido: a comparação
foi feita por fingerprint (`sha256[:12]`).

## A. Segurança

### A.1 `EMAIL_AGENT_TRIGGER_SECRET`: onde o valor ainda existe

Método: o valor foi recuperado **em memória** de um transcript onde já tinha vazado e buscado por igualdade.
Saída só com caminhos, contagens e fingerprint `sha256:9f2b599d0911`. No Supabase, a comparação foi feita por hash via SQL
(`encode(sha256(literal))[:12]`). Foram varridos 25.406 arquivos locais (exceto `.env*`, que **não foram abertos**) e o
histórico git de 20 clones.

| # | Local | Evidência | Classificação |
|---|---|---|---|
| 1 | `~/.claude/skills/integrar-email-agent/SKILL.md` | — | **já removido** na fase anterior (0 ocorrências) |
| 2 | **Supabase `relatorios-raw`**, função `public.notificar_problema_evento` | literal no corpo, fp = `9f2b599d0911`, sem Vault | **exige rotação** (código de produção) |
| 3 | **Supabase `Gente & Gestao`**, funções `notificar_rh_decisao_diarista`, `notificar_movimentacao_email`, `vigia_automacoes`, `notificar_aprovador_diarista`, `rp_enviar_alertas_faltas` | literal no corpo, fp = `9f2b599d0911` nas 5, sem Vault | **exige rotação** (código de produção) |
| 4 | **GitHub `tatiana-kelly/sousaleisamar` (privado)**, commit `8ed2b47` (06/08) em `origin/main`, `supabase/migrations/20260806204500_email_agent_movimentacao.sql` | `git log -S` / `git grep` no clone | **exige rotação** (histórico versionado: reescrever não é recomendado, a rotação torna o valor inerte) |
| 5 | 12 transcripts locais do Claude Code (`~/.claude/projects/`: sessões de ROTA-PEOPLE 29x/18x, ssw-relatorios 19x/1x/1x, DRE 3x, Torre 1x, `C--` 2x/6x/2x, esta sessão 2x) + 1 `auto-mode-classifier-error.txt` | igualdade de valor | **pode ser removido/redigido com segurança** (nenhum sistema depende). Só resolve de fato **depois** da rotação |
| 6 | Clone temporário `Temp/claude/C--ssw-relatorios/12f9399e…/scratchpad/sousaleisamar` | arquivo de migration | **pode ser removido com segurança** (cópia temporária) |
| 7 | `.env*` (51 arquivos, **não abertos**) — em especial `C:\ssw-relatorios\.env` + 2 backups `.env.bak-*` e `.env` em scratchpads temporários | não verificável sem abrir | **tratar como potencial** na rotação: atualizar os ativos e apagar backups/cópias temporárias |

Verificado **sem** o valor: nenhum commit nos demais 19 clones (AGENTE-I.A, Torre ×5, DRE, Devolucao-031-emissao/ssw-relatorios,
pendency-tracker, dp-vision-board, sousaleisamar-git local, …), nenhum arquivo de código/doc fora dos transcripts, nenhum
cron job nem função em `pendency-tracker`, `sal-ai-orchestrator` ou `Fogo no altar`.

### A.2 Sistemas que dependem do segredo

| Papel | Sistema | Onde a credencial vive | Confirmação |
|---|---|---|---|
| **Receptor** (valida o header `x-trigger-secret`) | Edge Function `email-agent` em `relatorios-raw` | Supabase → Project Settings → Edge Functions → Secrets → `EMAIL_AGENT_TRIGGER_SECRET` | documentado na skill oficial; código não lido de propósito, para não trazer o valor ao transcript |
| Chamador (trigger SQL) | `relatorios-raw.public.notificar_problema_evento` | literal no corpo da função | **confirmado por hash** |
| Chamadores (triggers SQL) | 5 funções em `Gente & Gestao` (item 3 acima) | literal no corpo | **confirmado por hash** |
| Chamador provável (Edge) | `relatorios-raw/enviar-alertas-regime` | Secret `EMAIL_AGENT_SECRET` (segundo a skill) | provável |
| Chamadores prováveis (Edge) | `Gente & Gestao/enviar-email-notificacao`, `notify-dp-movimentacao`, `aprovar-diarista-email` | Secrets do projeto | provável (nomes) |
| Chamador local | `C:\ssw-relatorios\alertas_faltas_d2.py` (tarefa `SAL\AlertasFaltasD2`, **desabilitada**) | `EMAIL_AGENT_SECRET` do `C:\ssw-relatorios\.env` | confirmado pelo código (nome) |
| Não dependem | Hermes Autonomy (usa o Email Agent **local em Python**, via Gmail API, sem header), AI Orchestrator, SAL OS | — | confirmado |

### A.3 Rotação — **HUMAN_REQUIRED** (não executada)

Onde a **nova** credencial deve ser configurada, sem nunca colar o valor em arquivo versionado, Skill, doc ou chat:

1. Gerar o valor novo (≥ 32 caracteres aleatórios) no gerenciador de segredos da Tatiana.
2. **Vault do Supabase** em `relatorios-raw` **e** em `Gente & Gestao`: `vault.create_secret(<novo>, 'email_agent_trigger_secret')`.
3. **Reescrever as 6 funções** para ler `(select decrypted_secret from vault.decrypted_secrets where name='email_agent_trigger_secret')`
   em vez do literal. É uma migration (**aprovação obrigatória**); versionar a migration **sem** o valor.
4. **Receptor**: Secret `EMAIL_AGENT_TRIGGER_SECRET` da Edge Function `email-agent` (`relatorios-raw`). Para evitar janela
   de falha, aceitar temporariamente antigo **ou** novo (alteração pequena no `email-agent`, também com aprovação) e remover
   o antigo depois de todos os chamadores migrarem.
5. **Chamadores Edge**: Secret `EMAIL_AGENT_SECRET` em `relatorios-raw` e nos projetos que chamam (`Gente & Gestao` e
   qualquer outro criado pelo "cenário C" da skill).
6. **Local**: `EMAIL_AGENT_SECRET` em `C:\ssw-relatorios\.env`. Apagar `.env.bak-*` e os `.env` de scratchpads temporários.
7. Validar cada fluxo com um envio de teste (**autorização para enviar e-mail**) e registrar no `email_agent_log.csv`.
8. Depois da rotação: redigir ou apagar os 12 transcripts e o clone temporário (item 5/6). O commit `8ed2b47` fica inerte.

### A.4 Outros achados de segurança (mesmo antipadrão, segredos diferentes)

- `relatorios-raw.cron.job` guarda **3 outros segredos de gatilho literais** (fingerprints distintos, nenhum é o do Email
  Agent) nos jobs `ingerir-455-ssw-diario` (inativo), `enviar-resumo-455-diario`, `classificar-regime-diario` e
  `enviar-alertas-regime-diario`. Recomendação: mesma migração para Vault (**HUMAN_REQUIRED**, migration).
- Bypass Resend em `enviar_resumo_455.py`: **corrigido** na fase anterior (working tree de `ssw-relatorios`, sem commit).
  O caminho serverless ativo é o cron `enviar-resumo-455-diario` → Edge `enviar-resumo-455`, que **ainda precisa ser
  verificado** (código não lido nesta fase).
- Segredos em código/log do Hermes Autonomy: **0 reais** (varredura da fase anterior + suíte de testes).

## B. Governança

Hermes = **DETECT → DIAGNOSE → REPAIR → VALIDATE → RECORD**. Nada além.

| Regra | Como está garantida |
|---|---|
| Só reparo técnico de risco baixo, explicitamente autorizado | ação em `allowed_recovery_actions` + `idempotent: true` + `DRY_RUN=false` + `AUTONOMOUS_REPAIR=true` + janela + circuito fechado. **Teto fixo em código** `GOVERNANCE_MAX_RISK = "low"`, que a config não consegue relaxar (`test_risk_ceiling_cannot_be_raised_by_config`) |
| Ações de baixo risco são só técnicas | `rerun_task`, `rerun_command`, `restart_task`, `cleanup_temp`, `validate_output` (`test_low_risk_actions_are_only_technical`) |
| Nunca decisão/aprovação/ação empresarial nem `verified_ok` de negócio | o vocabulário do motor não tem `APPROVED`/`VERIFIED_OK`/`DECISION` (`test_engine_vocabulary_has_no_business_decision_states`); o código não escreve `verified_ok`/`approved_decision`/`execute_action` (`test_engine_code_has_no_business_approval_writes`); o contrato trava `authority.*` em `false` |
| Não chama IA | nenhum cliente de LLM ou `/v1/agent-runs` no motor (`test_engine_code_never_calls_ai`) |
| Autonomia 24/7 desligada | `dry_run=true`, `autonomous_repair=false`, gateway Hermes parado, ticker não instalado (verificado em 18/09) |

## C. Divisão de responsabilidades

| Tema | Hermes | SAL Intelligence OS | AI Orchestrator |
|---|---|---|---|
| Objeto | execução de AUTOMAÇÕES | desvios do NEGÓCIO | chamadas de IA |
| Decide | se uma execução técnica atingiu o esperado; qual reparo técnico autorizado aplicar | o que fazer diante de impacto empresarial; aprovação humana; `VERIFIED_OK` | provedor, perfil, custo e segurança de cada chamada |
| **Chamar IA?** | **não decide**: publica `ai_review_signals` (evidência) | decide (gate `ai` do Decision Router) | decide/limita (`evaluateExecution`, `CostController`) |
| Memória | técnica (SQLite local) | empresarial/decisional (`decision_router.*`) | resultado de IA (`ai_evidence`, `ai_agent_run_audit`) |
| Notificação | outbox + **só** Email Agent | não notifica (fase atual) | não notifica |
| Scheduler | cron nativo Hermes | nenhum | nenhum |

### Notificação externa: só o Email Agent (verificado)
- Canais no código instalado: `TerminalChannel` e `OutboxChannel` (internos) e `EmailAgentChannel`, o **único** externo.
- `hermes_send`/`HermesSendChannel`: **0 ocorrências** no código-fonte, na cópia instalada (`%LOCALAPPDATA%\hermes\autonomy\app`), na config, nos wrappers e nas Skills.
- Nenhum SMTP/Resend/WhatsApp/Mattermost/Telegram/Slack/SendGrid/Twilio no motor. As menções que existem no registry **descrevem automações supervisionadas** (ex.: cobrança WhatsApp da Torre), não canais do Hermes.
- Cron jobs Hermes: `Deliver: local` nos dois. Config instalada: `channels:["outbox"]`, `external_enabled:false`.

### Memória
- Hermes SQLite = memória **técnica** de incidentes.
- SAL OS = memória **empresarial/decisional**.
- **Nenhuma sincronização ou cópia** existe ou foi criada.

## D. Contrato `AUTOMATION_INCIDENT` (`sal.automation-incident/1.0`)

Revisão da Fase 2:
- `ai_review_signals` (obrigatório): `unknown_cause`, `confidence`, `conflicting_evidence{present,cause_codes}`, `repeated_failure{present,count_window,window_hours,auto_recovered_same_cause,circuit_breaker_open}` e `actions_attempted`. São só fatos, sem chave de decisão (`call/should/recommend/trigger` são proibidas por teste).
- `routing_context` (obrigatório): o que o SAL OS precisa para montar o `AlertEnvelope`.
- Todo objeto é **fechado** (`additionalProperties:false` ou `propertyNames` restrito). Não existe mapa livre por onde `verified_ok` possa entrar.

Suficiência para **Hermes → SAL OS → Decision Router** (o mapeamento é do SAL OS):

| `AlertEnvelope` / `AlertBase` | Origem no contrato |
|---|---|
| `engine_source` | `source` = `hermes-autonomy` |
| `entity_type` / `entity_id` | `routing_context.entity_type` (`automation`) / `entity_id` |
| `evaluated_at` | `timestamp` |
| `rules_version` | `routing_context.registry_version` |
| `alert.period` | `routing_context.period` |
| `alert.severity` (low…critical) | `severity` P3→low, P2→medium, P1→high, P0→critical |
| `alert.title` | `automation_name` + `incident_type` |
| `alert.current_value` / `reference_value` | `routing_context.stale_hours` / `max_age_hours` |
| `alert.source_quality` / `quality_inputs` | `routing_context.evidence_completeness_pct`, `last_success_at`, `max_age_hours` |
| `missing_data` | `routing_context.missing_data` |
| `alert.metric_id` | **a definir pelo SAL OS**: `MetricPolicy` "automation_reliability" (sem ela o `case_type` vira UNKNOWN e os agentes ficam bloqueados) |
| `loop`, `approval_flags`, `priority_dimensions` | calculados pelo SAL OS |

Proibições comprovadas por teste (`test_forbidden_keys_rejected_at_any_depth`): o validador rejeita a injeção de
`verified_ok`, `approved_decision` e `executeAction` na raiz; de `verified_ok` em `validation`; de `approvedDecision` em
`diagnosis`; de `VERIFIED_OK` como critério; de `should_call_ai`; de `authority.can_approve_business_decision=true`; e de
`validation.status="VERIFIED_OK"`.

## E. Banco / memória — recomendação Supabase

**A ambiguidade:** docstrings do SAL OS (`decision_router/memory/postgres.py`, `repository.py`, `recorder.py`, `__init__.py`)
dizem "não há projeto Supabase aprovado para o SAL OS (D4)", mas o header de `memory/sql/001_decision_router_memory.sql`
diz "Destino autorizado: projeto Supabase sal-ai-orchestrator (zkwfupxztxczeadrlsri), schema decision_router".

**O que existe de fato** (metadados lidos em 18/09, nada alterado):

| Projeto | Papel observado | Evidência |
|---|---|---|
| `sal-ai-orchestrator` (`zkwfupxztxczeadrlsri`, criado 17/08) | persistência do AI Orchestrator **e** memória do Decision Router | migrations `create_orchestrator_persistence`, `create_project_registry`, **`decision_router_memory` (20260917180008)**, `create_agent_runs`, `add_agent_run_capability`. Tabelas `decision_router.case_routes/pattern_stats/playbooks` (0 linhas, RLS on), `ai_agent_runs` e `ai_agent_run_audit` (2 linhas) |
| `relatorios-raw` (`fsswfealkyavtjfaleil`) | dados operacionais (SSW/455/ICMS/regime) + Edge Function `email-agent` | `connectors/supabase/operational_connector.py` lê daqui; 7 Edge Functions de relatórios/e-mail |
| `pendency-tracker`, `Gente & Gestao`, `Fogo no altar` | produtos independentes | fora do escopo (AGENTS.md) |

**Recomendação técnica:** a memória empresarial/decisional e os eventos do SAL OS ficam em **`sal-ai-orchestrator`**
(`zkwfupxztxczeadrlsri`), nos schemas próprios (`decision_router` já existe; eventos futuros em schema separado, de dono
SAL OS).
- É onde o schema já foi **aplicado com autorização**, e a decisão D4 existe na prática. O que falta é **fechar formalmente** e
  corrigir as docstrings desatualizadas.
- Fica ao lado de `ai_agent_run_audit`, o que dá rastreabilidade Decision Router ↔ chamada de IA sem cópia entre projetos.
- Mantém a separação de **dados operacionais** (`relatorios-raw`, que o SAL OS só **lê**) de **estado decisional**. O
  alternativo misturaria a memória de decisões com ingestão bruta e com as funções de e-mail que hoje contêm segredo literal.
- Não cria projeto novo e não cria banco novo.

Ressalvas:
1. o SAL OS precisa de credencial própria com escopo mínimo (sem `service_role` compartilhado com o Orchestrator);
2. a memória técnica do Hermes **continua fora** (SQLite local). Se um dia for para Postgres, é schema técnico separado,
   nunca `decision_router`.

## F. Runtime

Hermes local e SAL OS local são **desenvolvimento/MVP**. O Windows não é assumido como runtime 24/7. Detalhes, partes
específicas de Windows e caminho para produção: [runtime.md](runtime.md).

## G. HUMAN_REQUIRED

| # | Item | Por que humano | Bloqueia |
|---|---|---|---|
| G1 | **Rotacionar `EMAIL_AGENT_TRIGGER_SECRET`** (passos A.3) | credencial de produção compartilhada por 2 projetos + histórico GitHub | **sim**: bloqueia qualquer integração |
| G2 | Migration: 6 funções SQL passam a ler do Vault (e os 4 cron jobs com outros segredos) | migration de banco exige aprovação | sim (junto com G1) |
| G3 | Autorizar envio de teste do Email Agent (validar rotação e `enviar_resumo_455.py`) | enviar e-mail | não |
| G4 | Fechar formalmente D4: `sal-ai-orchestrator` como Supabase da memória/eventos do SAL OS; corrigir as docstrings "D4 pendente" no SAL OS; credencial própria de escopo mínimo | decisão estrutural | sim, para a fase de integração |
| G5 | Escolher destinatário do Email Agent e ligar `external_enabled` | notificação real | não |
| G6 | Runtime 24/7 (host sempre ligado; gateway `systemd` ou ticker) | infraestrutura/custo | não, até a integração |
| G7 | Confirmar idempotência das automações `unverified` | regra de negócio de cada rotina | não |
| G8 | Commit de `enviar_resumo_455.py` no repo `ssw-relatorios` (tem WIP da Tatiana) | repo de outro fluxo | não |
| G9 | Verificar a Edge `enviar-resumo-455` (possível Resend) | fora do escopo desta fase | não |
| G10 | Push/PR da branch `feat/hermes-autonomy` | aprovação por vez | — |

## H. Próximo passo recomendado

**Primeiro, antes de qualquer integração:** executar a rotação do `EMAIL_AGENT_TRIGGER_SECRET` (G1) com a migração dos
6 triggers para Vault (G2), porque hoje ele está literal em código SQL de produção e em transcripts locais. Depois disso:

1. Tatiana fecha D4 (G4) e aprova a próxima fase.
2. **Fase 3 (Hermes, sem integração):** builder que gera `AUTOMATION_INCIDENT` a partir do `Store`, validado contra o
   schema, gravando só no outbox local. Sem consumidor, sem IA.
3. **Fase 4 (SAL OS, shadow):** adapter somente leitura evento → `AlertEnvelope` + `MetricPolicy` "automation_reliability",
   rodando em shadow sobre incidentes sintéticos (sem os 112 casos reais).
4. Só então: decidir o runtime 24/7 (G6) e ligar o Email Agent como canal (G5).
