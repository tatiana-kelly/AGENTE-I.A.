# Alinhamento de arquitetura — Hermes Autonomy × SAL Intelligence OS × AI Orchestrator

Data: 18/09/2026 · Fase: ALINHAMENTO (sem funcionalidade nova, sem integração, sem IA, sem deploy, sem push).

## Fronteira

| Sistema | Responsabilidade | Nunca faz |
|---|---|---|
| **Hermes Autonomy** | confiabilidade das AUTOMAÇÕES: DETECT → DIAGNOSE → REPAIR → VALIDATE → RECORD | decisão empresarial, Decision aprovada, `verified_ok` de negócio, ação empresarial, substituir aprovação humana |
| **SAL Intelligence OS** | decisão sobre DESVIOS DO NEGÓCIO: Decision Router → decision cycle → aprovação humana → verificação → learning → playbooks | monitorar execução de scripts |
| **AI Orchestrator** | runtime técnico de IA: roteamento de provedores, `evaluateExecution`, custo, `/v1/agent-runs` | decidir negócio, agendar, notificar |

## O que existe hoje (evidência da auditoria)

**SAL OS** (`sal-intelligence-os/backend/app`, maior parte WIP não versionado): `decision_router/` (`DecisionRouter.route(AlertEnvelope) → DecisionRoute`,
contrato `sal.decision-route/1.0`, gates loop→quality→rule→memory→similar→decision→learning→playbook→ai, fingerprint `fp/1`,
modo shadow), `decision_cycle/` (20 `CaseState`, `ApprovalService` só humano GESTOR/DIRETORIA, `VERIFIED_OK` só por Verifier,
`LearningService`, playbooks com aprovação humana), memória de casos no schema Supabase `decision_router`
(`case_routes`, `pattern_stats`, `playbooks`), `AuditTrail` JSONL, `agent_bridge/` (cliente de `/v1/agent-runs`), 26 agentes de
negócio. **Não tem**: scheduler, notificação (`EscalationEvent.notified: Literal[False]`), endpoint de ingestão de eventos.

**AI Orchestrator** (`src/`): `classifyTask/routeTask/planTask/orchestrate`, `evaluateExecution` (READ_ONLY/DRY_RUN padrão),
`CostController`, tabelas `ai_tasks/ai_runs/ai_evidence/ai_projects/ai_project_permissions`, `/v1/agent-runs`
(`sal.agent-run/1.0`, HMAC, `agent_authority{can_approve:false, can_execute:false}`, chaves proibidas `approved_decision`,
`execute_action`, `executed_action`, `verified_ok`), `ai_agent_run_audit`. **Não tem**: scheduler, notificação.

## 1. Mapa de componentes

Legenda: **KEEP_HERMES** · **REUSE_EXISTING** · **SHARED_INTERFACE** · **DUPLICATE_AVOID** · **REFACTOR_LATER**

| Componente | Hermes (o que foi construído) | SAL OS | AI Orchestrator | Decisão |
|---|---|---|---|---|
| Supervisão EXPECTED vs ACTUAL | `guardian.py` — execução/saída/entrega de automações | inexistente (alertas são desvios de MÉTRICA de negócio) | inexistente | **KEEP_HERMES** |
| Classificação de incidente técnico | 15 `IncidentType` | `case_type` de negócio (14 tipos) | `classifyTask` (tipo de tarefa de IA) | **KEEP_HERMES** — vocabulários distintos, sem sobreposição |
| Diagnóstico | `diagnostician.py` + `knowledge.py` (regras determinísticas, 12 passos) | investigação de negócio via agentes (`INVESTIGATE_FIRST`) | `/v1/agent-runs` (investigação por LLM) | **KEEP_HERMES** para causa técnica conhecida; **REUSE_EXISTING** (`/v1/agent-runs`) quando a regra não resolve — ver §5 |
| Reparo | `repair.py` — só ações técnicas de baixo risco (`rerun_task`, `rerun_command`, `restart_task`, `cleanup_temp`) | `action_link` — ação EMPRESARIAL com aprovação humana | `evaluateExecution` para efeitos de IA | **KEEP_HERMES**, restrito a ação técnica; ação empresarial é exclusiva do SAL OS |
| Validação | `validator.py` — reexecuta a verificação técnica | `verification.py` — `VERIFIED_OK` de resultado de negócio | validação de output de IA | **KEEP_HERMES** com vocabulário próprio (`TECHNICAL_OK`); **nunca** `verified_ok` |
| Escalonamento | `escalator.py` — mensagem técnica acionável | `EscalationEvent` (não notifica) | — | **SHARED_INTERFACE**: incidente técnico → Email Agent; impacto de negócio → evento `AUTOMATION_INCIDENT` para o SAL OS decidir |
| Notificação | `notify.py` — outbox + canal `email_agent` | inexistente | inexistente | **REUSE_EXISTING** (Email Agent oficial). Canal `hermes_send` (WhatsApp/Mattermost via Hermes) **removido** = **DUPLICATE_AVOID** |
| Scheduler | cron nativo Hermes (`--no-agent`), 2 jobs | inexistente (planeja pg_cron para `refresh_overdue`) | inexistente (sem `crons` no vercel.json) | **REUSE_EXISTING** (Hermes cron). Nenhum scheduler novo. O "ticker" é só o gatilho do cron Hermes, não um scheduler |
| Memória | SQLite `autonomy.db` — incidentes técnicos, tentativas, circuito | memória de casos/decisões (`decision_router.*` no Supabase) | memória de resultado de IA (`ai_evidence`) | **KEEP_HERMES** como memória TÉCNICA local; **não** é memória empresarial — ver §2 |
| Aprendizado | `skill_candidates` (causa técnica → ação técnica validada) | `LearningService`, `pattern_stats` | — | **KEEP_HERMES** escopo técnico · **REFACTOR_LATER**: renomear para `remediation_candidates` (evitar confusão com learning de negócio) |
| Playbooks | nenhum (Skills Hermes são manuais de operação) | playbooks de decisão com aprovação humana | — | **DUPLICATE_AVOID**: Hermes não cria playbook de decisão |
| Prioridade | P0–P3 = severidade técnica | `priority{score,label}` de negócio | — | **KEEP_HERMES** como `severity` técnica; prioridade de negócio é do SAL OS · **REFACTOR_LATER**: renomear campo interno `priority` → `severity` |
| Agrupamento por causa raiz | `ROOT_CAUSE_INCIDENT` técnico | fingerprint `fp/1` / `pattern_key` de caso de negócio | — | **KEEP_HERMES** (domínios diferentes) |
| Idempotência / loop | fingerprint automação+janela, circuit breaker, rate limit | `loop_guard` (hop/reopen de caso) | idempotency_key de agent-run | **KEEP_HERMES** |
| Auditoria | `audit_log` técnico (SQLite) | `AuditTrail` JSONL (decisões) | `ai_agent_run_audit`, `ai_evidence` | **KEEP_HERMES** técnico; **SHARED_INTERFACE**: evento leva `audit_ref` |
| Orquestração de IA | nenhuma (motor sem LLM; agente LLM do próprio Hermes NÃO usado no ciclo) | `agent_bridge` → `/v1/agent-runs` | runtime oficial | **REUSE_EXISTING** (`/v1/agent-runs`); usar o LLM nativo do Hermes para diagnóstico seria **DUPLICATE_AVOID** |
| "Agentes" hermes-* | 5 módulos determinísticos (não são agentes LLM) | 26 agentes de negócio | provedores (openai/anthropic/…) | **KEEP_HERMES**; nenhum agente especialista de negócio criado |
| Skills Hermes | `automation-guardian`, `incident-memory`, `register-automation` | — | — | **KEEP_HERMES** (operação técnica) |
| Registry | `registry/automations.json` | `domain-routing.yaml`, `MetricPolicy` | `AI-PROJECT.yaml` / `ai_projects` | **KEEP_HERMES** · **REFACTOR_LATER**: campos `project_id` e `business_impact` por automação |
| Relatório diário | "HERMES AUTOMATION HEALTH" (saúde técnica) | stats de ciclo | — | **KEEP_HERMES**, entregue via Email Agent (tag `RESUMO DIÁRIO`) |
| Contrato de integração | `contracts/automation_incident.v1.schema.json` | entrada real = `AlertEnvelope` (pull adapters) | `sal.agent-run/1.0` | **SHARED_INTERFACE** (§6) |
| Canário / testes | `canary.py`, 46 testes | — | — | **KEEP_HERMES** |

## 2. Memória

- `autonomy.db` (SQLite local) **permanece**, porque é memória técnica operacional do Guardian: idempotência por janela,
  tentativas, circuit breaker, dedupe de notificação e histórico de causas técnicas. Nenhum dado de decisão empresarial
  é gravado nele, e nenhum banco novo é criado.
- **Não** duplicar `decision_router.case_routes/pattern_stats/playbooks`.
- **Futuro (não implementado):** o SAL OS só toma conhecimento de incidentes que tenham `requires_business_decision=true`,
  via evento `AUTOMATION_INCIDENT` (§6). Dois caminhos possíveis, e os dois seguem o padrão que o SAL OS já usa:
  1. **pull (recomendado):** o Hermes grava eventos em `%LOCALAPPDATA%\hermes\autonomy\events\automation_incidents.jsonl`
     (append-only). Um adapter no SAL OS, no estilo dos `adapters/torre_*.py`, lê o arquivo e monta um `AlertEnvelope`
     (`engine_source="hermes-autonomy"`) em modo shadow.
  2. **consulta:** o SAL OS consulta o histórico técnico em modo somente leitura (`ha.py history/incident`), sem
     replicar tabelas.
  A persistência como CASO é do SAL OS, que decide no próprio schema `decision_router`.
- Pendência que não bloqueia: `postgres.py` diz que não existe projeto Supabase aprovado para o SAL OS (D4), mas o
  header do SQL diz que o schema foi aplicado no projeto do Orchestrator. **HUMAN_REQUIRED** resolver isso antes da fase 3.

## 3. Scheduler

Continua o cron nativo do Hermes (`hermes-autonomy-guardian` a cada 30 min, `hermes-autonomy-daily-report` às 10:00).
Não existe e não será criado outro scheduler. As automações continuam no Agendador do Windows, onde já estavam; o Hermes só observa.
Falta decidir o gatilho do cron Hermes (ticker `hermes cron tick` ou gateway) — **HUMAN_REQUIRED**, sem mudança.

## 4. Notificação

- Hermes grava sempre no **outbox** e usa **só o Email Agent** como canal externo (desligado até a Tatiana escolher o destinatário).
- `hermes_send` foi removido, porque seria um segundo sistema de mensagens.
- O Python do Hermes tem `googleapiclient`, então o canal `email_agent` funciona dentro do cron.
- **Bypass corrigido:** `C:\ssw-relatorios\enviar_resumo_455.py` deixou de chamar `api.resend.com` e passou a usar
  `agents.email_agent.enviar_email(tag="RESUMO DIÁRIO", assunto_literal=True, corpo_html=True)`. Consulta, HTML,
  destinatários, CC e assunto continuam idênticos. A ligação foi verificada sem envio real (função espiã). Contexto:
  o script está dormente, porque o envio diário do 455 passou para o `pg_cron` segundo `pipeline_runner.py` e o único
  chamador hoje é `backfill_abril.bat`. A alteração ficou **no working tree, sem commit** no repo `ssw-relatorios`, que
  tem WIP da Tatiana. `RESEND_API_KEY` no `.env` **não foi tocado**: segundo a skill oficial, só é removido depois do
  primeiro envio confirmado.
- **A verificar** (fora do escopo pedido): o caminho serverless (`pg_cron`) do e-mail do 455 também pode estar fora
  do Email Agent.

## 5. IA — o Hermes fornece evidência, a camada de decisão decide (revisado na Fase 2)

O Hermes **não chama IA** e **não decide quando uma chamada de IA vale o custo**: nenhum limiar de "chamar IA" fica fixo
dentro do Hermes (teste `test_engine_code_never_calls_ai`). O que ele faz é publicar, no contrato, o bloco
`ai_review_signals`, com fatos apenas:

| Sinal | Como o Hermes deriva (determinístico) |
|---|---|
| `unknown_cause` | `diagnosis.cause_code == "UNKNOWN_CAUSE"` |
| `confidence` | confiança do diagnóstico (0–1) |
| `conflicting_evidence{present, cause_codes}` | ≥ 2 causas catalogadas de tipos diferentes com evidência no mesmo incidente (`cause_hits`) |
| `repeated_failure{present, count_window, window_hours, auto_recovered_same_cause, circuit_breaker_open}` | falhas na janela do circuit breaker e quantas vezes a mesma causa foi "recuperada" (recorrência mascarada) |
| `actions_attempted` | total de tentativas técnicas executadas/simuladas |

**Quem decide:** o SAL OS (Decision Router, gate `ai`) e/ou o AI Orchestrator (`evaluateExecution`, `CostController`)
decidem se chamam, qual perfil e com qual orçamento. A política de limiar pertence a eles, que podem mudá-la sem tocar no Hermes.
Se decidirem chamar, o resultado (hipóteses) volta como contexto para o humano/SAL OS, e **não** amplia a matriz de
reparo do Hermes nem dispara ação.

Pré-requisitos, se a camada de decisão quiser que o próprio Hermes apareça como principal no futuro (**HUMAN_REQUIRED**):
principal `service:hermes-autonomy` em `AGENT_RUN_PRINCIPALS`, `project:grant` com `agent_run` e segredo HMAC pelo ambiente.

## 6. Interface — contrato `AUTOMATION_INCIDENT` (só contrato)

- Arquivos: `contracts/automation_incident.v1.schema.json`, `contracts/automation_incident.example.json`, testado por `tests/test_contract.py`.
- Identificação: `sal.automation-incident/1.0`, `event_id = sha256(incident_id|lifecycle_state)`.
- Campos obrigatórios: `event_id`, `automation_id`, `timestamp`, `severity`, `incident_type`, `expected`, `actual`, `evidence`, `diagnosis`, `confidence`, `actions_attempted`, `validation`, `recurrence`, `requires_human`, `requires_business_decision`, `authority`.
- Salvaguardas de governança no próprio contrato:
  - `validation.scope` é `"technical"` e o status usa `TECHNICAL_OK`, nunca `verified_ok`;
  - `authority.can_approve_business_decision`, `can_execute_business_action` e `can_declare_business_verified` são `const false`;
  - `approved_decision`, `execute_action`, `executed_action` e `verified_ok` são proibidas em qualquer nível. É a mesma lista do Orchestrator, e o teste falha se alguma aparecer.

Regra proposta para `requires_business_decision=true`, que também **não foi implementada**. Vale só quando o registry marca a automação como
fonte de dado ou entrega usada em decisão (`business_impact`) **e** o incidente terminou `ESCALATED` ou `CIRCUIT_BREAKER_OPEN`
**e** o dado ou a entrega está ausente, desatualizado ou suspeito além da janela. O Hermes relata o fato e o SAL OS decide.

Mapeamento futuro, que é responsabilidade do SAL OS: evento → `AlertEnvelope{engine_source:"hermes-autonomy", entity_type:"automation",
entity_id: automation_id, missing_data, quality_inputs.last_updated_at}` → exige `MetricPolicy` própria (senão `case_type UNKNOWN` bloqueia agentes).
Sem conexão com os 112 casos do shadow run.

## 7. Governança

O Hermes **pode** corrigir uma automação técnica de baixo risco **quando explicitamente autorizado**. Isso exige, ao mesmo tempo:
- ação listada em `allowed_recovery_actions`;
- `idempotent: true`;
- `DRY_RUN=false` + `AUTONOMOUS_REPAIR=true`;
- janela de reparo válida e circuito fechado.

O Hermes **nunca** aprova decisão empresarial, executa ação empresarial, declara `verified_ok` de resultado de negócio ou
substitui aprovação humana. Isso fica garantido por quatro coisas:
- o vocabulário do motor (não existe estado `APPROVED` nem `VERIFIED_OK`);
- a matriz do Reparador, que só tem ações técnicas;
- o contrato (`authority` com `const false` e chaves proibidas);
- os testes (`test_contract.py`, `TestSafetyRails`).

## 8. Segurança

| Item | Status |
|---|---|
| Segredo `EMAIL_AGENT_TRIGGER_SECRET` literal em `~/.claude/skills/integrar-email-agent/SKILL.md` | **Corrigido**: valor removido e substituído por referência ao secret manager. Varredura sem imprimir o valor: 0 outras cópias fora de `.env*` |
| Rotação desse segredo | **HUMAN_REQUIRED (bloqueador)**: o valor ficou em texto puro na skill e aparece em transcripts locais de sessões do Claude Code que leram o arquivo. A rotação exige atualizar os Secrets de ≥ 2 projetos Supabase (`relatorios-raw` e outros que chamam o `email-agent`) ao mesmo tempo. Não foi rotacionado automaticamente |
| Bypass do Email Agent em `enviar_resumo_455.py` | **Corrigido** (§4). Pendente: 1 envio real de teste (**precisa de autorização**, porque envia e-mail) e depois remover `RESEND_API_KEY` do `.env` |
| Segredos em código/log do Hermes Autonomy | Varredura em 104 arquivos (código, docs, estado, outbox, saídas do cron): **0 reais**. 3 falsos positivos: nome da variável `GITHUB_TOKEN` e valores falsos do teste de redação |
| Observação (fora do escopo) | `/v1/agent-runs` usa `InMemoryNonceStore`, o que dá proteção a replay por instância serverless. Vale revisar antes de ligar o Hermes |

## 9. Arquitetura final

```text
AUTOMAÇÃO (Agendador do Windows / GitHub Actions / scripts — inalteradas)
  ↓ evidências (estado da tarefa, logs, arquivos, APIs)
HERMES GUARDIAN   (cron nativo Hermes, --no-agent, determinístico)
  ↓
INCIDENT técnico  (autonomy.db — memória técnica local)
  ↓
[técnico] DIAGNOSTICIAN → REPAIR (baixo risco, autorizado) → VALIDATOR (TECHNICAL_OK/FAIL)
  │        └─ causa desconhecida/ambígua → AI Orchestrator /v1/agent-runs (hipóteses; sem autoridade)   [fase 4]
  ├─ resolvido            → RECORD (audit_log) · relatório diário via Email Agent
  ├─ ação humana técnica  → Escalator → Email Agent (credencial, permissão, dependência)
  ↓
[impacto empresarial: requires_business_decision=true]
AUTOMATION_INCIDENT (sal.automation-incident/1.0)                                                   [fase 1–3]
  ↓
SAL INTELLIGENCE OS  (adapter → AlertEnvelope, shadow)
  ↓
DECISION ROUTER → decision cycle → APROVAÇÃO HUMANA (GESTOR/DIRETORIA) → Verifier → learning/playbook
  ↓
AI ORCHESTRATOR  somente quando o Router decide (ONE_AGENT/MULTI_AGENT via agent_bridge)
```

## 10. Plano de integração sem duplicação (nada implementado nesta fase)

| Fase | Entrega | Dono | Pré-requisito |
|---|---|---|---|
| 0 (feita) | auditoria, contrato, remoção de `hermes_send`, correção do bypass 455, limpeza do segredo | Claude Code | — |
| 1 | Hermes emite `AUTOMATION_INCIDENT` num outbox JSONL local (builder a partir do `Store` + teste de contrato) | Hermes | OK da Tatiana |
| 2 | registry ganha `project_id` + `business_impact`, e a regra de `requires_business_decision` é implementada | Hermes | Tatiana define quais automações alimentam decisão |
| 3 | adapter de leitura no SAL OS (evento → `AlertEnvelope`, shadow) + `MetricPolicy` "automation_reliability" | SAL OS | resolver D4 (projeto Supabase) |
| 4 | diagnóstico assistido por `/v1/agent-runs` para `UNKNOWN_CAUSE` | Hermes → Orchestrator | principal + grant + segredo HMAC; nonce store persistente |
| 5 | Email Agent como canal externo ligado | Hermes | destinatário escolhido |

REFACTOR_LATER (sem pressa):
- `skill_candidates` → `remediation_candidates`;
- campo `priority` → `severity`;
- `project_id` no registry.
