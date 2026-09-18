# Ponte Hermes → SAL OS — arquitetura de integração (planejada, NÃO conectada)

## Fluxo

```text
AUTOMAÇÃO (Agendador do Windows / GitHub Actions — inalteradas)
  ↓
HERMES  DETECT → DIAGNOSE → REPAIR(baixo risco, autorizado) → VALIDATE → RECORD      [pronto]
  ↓  contract.build_event()  +  contract.validate_event()
AUTOMATION_INCIDENT  (sal.automation-incident/1.0, FINAL)                              [pronto]
  ↓  IncidentOutbox (append-only, idempotente por event_id, inválido → rejected.jsonl)
OUTBOX LOCAL  %LOCALAPPDATA%\hermes\autonomy\events\automation_incidents.jsonl       [pronto, desligado]
  ┆  ← fronteira: nada atravessa nesta fase
SAL OS READ-ONLY ADAPTER  (adapters/hermes_incident.py — dono: SAL OS)                [a construir]
  ↓  evento → AlertEnvelope (engine_source="hermes-autonomy", entity_type="automation")
DECISION ROUTER  gates: loop_guard → quality → rule                                   [existe, shadow]
  ↓
KNOWLEDGE GATE  memory → similar → decision → learning → playbook                     [existe]
  ↓  (reuso de conhecimento antes de qualquer IA; REUSE_DECISION/playbook exigem aprovação humana)
AI ORCHESTRATOR  gate "ai" → /v1/agent-runs  SOMENTE se o Router decidir               [existe]
  ↓
decision cycle → APROVAÇÃO HUMANA (GESTOR/DIRETORIA) → Verifier → learning
```

"Knowledge Gate" é o nome deste plano para o trecho `memory → similar → decision → learning → playbook` do
`DecisionRouter`. É lá que o SAL OS reaproveita casos, decisões e playbooks já conhecidos antes do gate `ai`.

## Regras da ponte

| Evento | O que o SAL OS faz (proposta, decisão do SAL OS) |
|---|---|
| `requires_business_decision=false` (técnico puro, **sem `metric_id`**) | registra como contexto/observabilidade. **Não** abre caso de decisão. A ação humana técnica já foi pedida pelo Hermes via Email Agent |
| `requires_business_decision=true` (com `metric_id` quando existir métrica) | adapter monta `AlertEnvelope` e o Decision Router roteia em **shadow** primeiro |
| `ai_review_signals` | insumo do gate `ai` e do `CostController`. O Hermes **não** decide chamar IA |

Mapeamento de campos: [hardening-phase2.md §D](hardening-phase2.md). `metric_id` exige uma `MetricPolicy` no SAL OS
(sem ela o `case_type` vira UNKNOWN e os agentes ficam bloqueados).

## Estado dos componentes

| Peça | Estado |
|---|---|
| Contrato `sal.automation-incident/1.0` | FINAL: schema + regras semânticas + exemplo + fixture Fechar Dia |
| `hermes_autonomy/contract.py` | construtor, validador, outbox local |
| Orchestrator → outbox | ligado por `outbox.enabled` (**false**) |
| CLI | `ha.py outbox list / validate <arquivo> / emit <incident_id>` |
| Consumidor / transporte / IA | **não existem** (por decisão) |

## Ordem de ativação (cada item com aprovação)

1. Rotação do `EMAIL_AGENT_TRIGGER_SECRET` ([secret-rotation-plan.md](secret-rotation-plan.md)): pré-requisito.
2. Ligar `outbox.enabled=true` (só local).
3. SAL OS: adapter somente leitura + `MetricPolicy` "automation_reliability", em shadow, primeiro com a fixture
   `tests/fixtures/fechar_dia_0x80070005` (sem casos reais novos).
4. Persistência de eventos no schema próprio do SAL OS em `sal-ai-orchestrator` ([D4](decisions/D4-supabase-sal-os.md)).
5. Runtime 24/7 fora do notebook ([runtime.md](runtime.md)).
