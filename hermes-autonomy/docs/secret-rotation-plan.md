# Plano de rotação — `EMAIL_AGENT_TRIGGER_SECRET` — **HUMAN_REQUIRED**

Nada foi alterado em produção e nenhuma credencial foi rotacionada. O valor nunca foi exibido: toda comparação foi feita
por fingerprint (`sha256[:12] = 9f2b599d0911`).

## 1. Auditoria final de dependências (18/09/2026)

| # | Onde | O que é | Disparo / quem usa | Tipo de dependência |
|---|---|---|---|---|
| R1 | `relatorios-raw` → Edge Function **`email-agent`** | **receptor**: valida o header `x-trigger-secret` | chamadas HTTP dos itens abaixo | Secret `EMAIL_AGENT_TRIGGER_SECRET` (Edge Functions → Secrets) |
| C1 | `relatorios-raw.public.notificar_problema_evento` | trigger SQL com **literal** | `event_issues` → `trg_notificar_problema_evento` | literal no corpo (confirmado por hash) |
| C2 | `Gente & Gestao.public.notificar_movimentacao_email` | trigger SQL com literal | `movimentacoes` → `trg_notificar_movimentacao_email` | literal (hash) |
| C3 | `Gente & Gestao.public.notificar_aprovador_diarista` | trigger SQL com literal | `diarista_solicitacoes` → `trg_diarista_notificar_aprovador` | literal (hash) |
| C4 | `Gente & Gestao.public.notificar_rh_decisao_diarista` | trigger SQL com literal | `diarista_solicitacoes` → `trg_diarista_notificar_rh_decisao` | literal (hash) |
| C5 | `Gente & Gestao.public.vigia_automacoes` | função com literal | sem trigger e sem cron: chamada por RPC/app | literal (hash) |
| C6 | `Gente & Gestao.public.rp_enviar_alertas_faltas` | função com literal | sem trigger e sem cron: chamada por RPC/app (provável `get-faltas-alertas`) | literal (hash) |
| C7 | `relatorios-raw` → Edge `enviar-alertas-regime` | chamador | cron `enviar-alertas-regime-diario` (11:00) | Secret `EMAIL_AGENT_SECRET` (**provável**, pela skill oficial) |
| C8 | `Gente & Gestao` → Edges `enviar-email-notificacao`, `notify-dp-movimentacao`, `aprovar-diarista-email` | chamadores | app/triggers | Secrets do projeto (**provável**, pelo nome) |
| C9 | `C:\ssw-relatorios\alertas_faltas_d2.py` | chamador local | tarefa `SAL\AlertasFaltasD2` (**desabilitada**) | `EMAIL_AGENT_SECRET` no `C:\ssw-relatorios\.env` |
| H1 | GitHub **privado** `tatiana-kelly/sousaleisamar`, commit `8ed2b47` (`origin/main`) | histórico: `supabase/migrations/20260806204500_email_agent_movimentacao.sql` | — | vazamento em histórico; fica inerte após a rotação |
| H2 | 12 transcripts locais do Claude Code + 1 clone temporário | vazamento local | — | remover/redigir **após** a rotação |
| H3 | `.env*` (não abertos): `C:\ssw-relatorios\.env`, `.env.bak-*` e scratchpads | possíveis cópias | — | atualizar os ativos e apagar backups/temporários |

**Correção de premissa:** os **4 `pg_cron` jobs** de `relatorios-raw` (`ingerir-455-ssw-diario` inativo,
`enviar-resumo-455-diario`, `classificar-regime-diario`, `enviar-alertas-regime-diario`) **não** contêm o
`EMAIL_AGENT_TRIGGER_SECRET`. Eles guardam **3 outros segredos de gatilho literais** (fingerprints distintos), com o mesmo
antipadrão. Entram no plano como **R-B** (rotação paralela, independente).

Infra disponível: Vault presente nos dois projetos (`relatorios-raw`: 0 segredos; `Gente & Gestao`: 4 segredos;
`pg_net` + `supabase_vault` instalados).

## 2. Plano seguro (sem janela de falha) — cada passo com aprovação

| Etapa | Ação | Onde configurar a nova credencial | Aprovação |
|---|---|---|---|
| 0 | Congelar: não criar novos chamadores com literal | — | — |
| 1 | Gerar o valor novo (≥ 32 chars aleatórios) no gerenciador de segredos | gerenciador da Tatiana (**nunca** em arquivo, Skill, doc, chat ou commit) | Tatiana |
| 2 | Receptor aceita **antigo OU novo** temporariamente | Edge `email-agent` (`relatorios-raw`): Secrets `EMAIL_AGENT_TRIGGER_SECRET` (novo) + `EMAIL_AGENT_TRIGGER_SECRET_PREVIOUS` (antigo); mudança pequena no código do `email-agent` | deploy de Edge (aprovação) |
| 3 | Criar o segredo no Vault | `vault.create_secret(<novo>, 'email_agent_trigger_secret')` em **`relatorios-raw`** e em **`Gente & Gestao`** | Tatiana (valor digitado por ela no SQL Editor) |
| 4 | Migration: C1–C6 passam a ler `vault.decrypted_secrets` (sem literal). A migration versionada **não contém o valor** | `relatorios-raw` (C1) e `Gente & Gestao` (C2–C6) | migration (aprovação) |
| 5 | Chamadores Edge | Secret `EMAIL_AGENT_SECRET` em `relatorios-raw` (C7) e `Gente & Gestao` (C8) | Tatiana |
| 6 | Chamador local | `EMAIL_AGENT_SECRET` em `C:\ssw-relatorios\.env` (C9); apagar `.env.bak-*` | Tatiana |
| 7 | Validar cada fluxo: 1 envio de teste por chamador; conferir `email_agent_log.csv` e Edge logs | — | autorização de envio de e-mail |
| 8 | Remover o aceite do valor antigo (`..._PREVIOUS`) do receptor | Edge `email-agent` | deploy (aprovação) |
| 9 | Limpeza local: redigir/apagar os 12 transcripts e o clone temporário (H2) | local | Tatiana |
| R-B | Mesmo procedimento para os 3 segredos dos `cron.job` (Vault + `cron.alter_job`) | `relatorios-raw` | migration (aprovação) |

**Rollback** de cada etapa: o receptor aceita os dois valores até a etapa 8. Qualquer chamador com problema volta a
funcionar reapontando para o valor antigo no Vault, sem redeploy.

**Critério de pronto:** 0 literais em `pg_proc`/`cron.job` (consulta por fingerprint), receptor aceitando só o novo,
7 fluxos com envio de teste registrado.
