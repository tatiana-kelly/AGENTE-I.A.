# DISCOVERY-REPORT.md — PRP-003: SAL AI OS / AI Orchestrator

**Data:** 2026-08-13
**Escopo:** Discovery read-only antes da implementação do AI Orchestrator / Multi-Model Router.
**Regra observada:** nada foi implementado, alterado ou commitado nesta fase. Nenhum código de produção foi tocado.

---

## 1. Arquitetura encontrada

Não existe hoje nenhuma camada de orquestração de IA multi-provider na SAL Express. O que existe é:

- **`C:\SAL_AI_OS\`** — Control Plane de *governança* (não é código), criado em 2026-08-10/11 para o PRP-001 (Master Inventory). Contém apenas registries, mapas e um Decision Log. Não contém nem deve conter código de produção (regra própria do projeto).
- **Três implementações de IA single-provider, isoladas, todas falando diretamente com a Anthropic API**, sem nenhuma camada de abstração:
  - `C:\Projeto ClaudeCode\core\agent.ts` — framework TS (`icms-pipeline-framework`) com `Agent`/`Pipeline`/`Subagent`, usa `@anthropic-ai/sdk` diretamente dentro da classe `Agent`. Roda loop agentic com tool-use, tem `PipelineContext.errors[]` (trilha de erro simples, não é evidence log).
  - `C:\ssw-relatorios\folha_ingestao\modules\intelligence\chat_agent.py` e `insights_generator.py` — usam `anthropic.Anthropic()` diretamente, com fallback determinístico sem IA (`_insight_sem_ia`) quando a chamada falha.
  - Nenhuma delas tem interface `Provider`/`LLMClient` — é chamada concreta, hardcoded a um único provider.
- **Nenhum `n8n` encontrado** em nenhum dos locais varridos (local filesystem nem Supabase). GAP já registrado em memória de sessões anteriores (`EVIDENCE_GAPS.md`), continua em aberto. Não foi possível confirmar se n8n roda no servidor Ubuntu 192.168.100.37 (sem acesso nesta sessão).
- **Nenhuma integração com Manus** encontrada em lugar nenhum.
- **Nenhum PRP-003 ou documento de orchestrator/router preexistente** — este é greenfield genuíno.

Duas implementações *conceituais* (não técnicas) de modos de execução (READ_ONLY/ASSISTED/AUTONOMOUS) já existem em prosa, e uma delas tem enforcement real em código:
- `CENTRO-DE-AGENTES-IA\CLAUDE.md` e `ssw-relatorios\CLAUDE.md` documentam a mesma regra ("descrever ação → esperar confirmação sim/ok/pode → executar → resumir"), mas só como instrução para o Claude Code, não como sistema.
- `ssw-relatorios\.claude\hooks\pre_tool_check.ps1` + `.claude\settings.json` — **hook `PreToolUse` real**, que classifica comandos Bash por regex em whitelist (leitura, sempre permitido) e blacklist (escrita/execução, bloqueado com `exit 2` até confirmação). É o único exemplo real de gating por modo de execução em todo o ecossistema local.

## 2. Projetos encontrados

| Projeto | Local | Relevância para PRP-003 |
|---|---|---|
| `C:\CENTRO-DE-AGENTES-IA` | Local, não é repo git | Hub de agentes documentado, mas na prática só tem o Email Agent implementado. CLAUDE.md define regra de confirmação. |
| `C:\Projeto ClaudeCode` | Local, contém sub-repos git (`Torre-de-Controle`, clones de `Devolucao-031-emissao` e `sousaleisamar-d0c8cbfd`) | Framework de agentes TS single-provider (Anthropic). Prior art de pipeline/agent/subagent, não de routing. |
| `C:\ssw-relatorios` | Repo git próprio, remote `github.com/tatiana-kelly/Devolucao-031-emissao.git`, branch `main`, **5 commits locais não empurrados + mudanças não commitadas** | 6 skills formais do Claude Code + hook de execution-mode gating real. Maior maturidade de engenharia dos três. |
| `github.com/tatiana-kelly/AGENTE-I.A.` (novo) | **Repositório de destino do PRP-003**, confirmado acessível via git local, **vazio (0 refs)** | Vai receber o código do Orchestrator. Clonado localmente em `C:\Users\tatiana.silva\AGENTE-I.A` para esta Discovery. |
| `pendency-tracker` (Supabase) | Cloud | Backend real do `tati-command-deck` (nome do projeto Supabase diverge do conteúdo — já registrado como ADR-pendente-05). **Tem o padrão de evidence/audit-log mais maduro encontrado** (ver seção 4). |
| `relatorios-raw` (Supabase) | Cloud | Núcleo de dados fiscais/SSW/folha. Sem tabelas relacionadas a IA/orchestrator. Candidato a fonte de dados para skills de análise fiscal, não para o core do orchestrator. |
| `Gente & Gestao`, `Fogo no altar` (Supabase) | Cloud | Não verificados a fundo nesta Discovery — o segundo já está marcado fora de escopo (ADR-pendente-03), o primeiro é de RH/DP, sem relação direta com o orchestrator. |

## 3. Integrações encontradas

- **Supabase**: 4 projetos ativos (`pendency-tracker`, `relatorios-raw`, `Gente & Gestao`, `Fogo no altar`), todos com RLS habilitado nas tabelas verificadas. `pg_cron` ativo em pelo menos 3/4 (achado de sessão anterior).
- **Email**: canal único oficial confirmado — `ia.sal@salexpress.com.br`, implementado em `CENTRO-DE-AGENTES-IA\agents\email_agent.py` (local) + Edge Function `email-agent` em `relatorios-raw` (cloud). Existe também `integrar-email-agent` skill já instalada nesta sessão do Claude Code, que documenta como qualquer automação nova deve usar esse agente em vez de implementar envio próprio.
- **GitHub**: conector MCP (`plugin:engineering:github`) **segue sem autenticação nesta sessão** (mesmo bloqueio de sessões anteriores, ADR-pendente-06 ainda não resolvida). **Path alternativo confirmado nesta sessão: git CLI local tem credenciais funcionando** para `github.com/tatiana-kelly/*` (testado com `git ls-remote` e `git clone` no repo `AGENTE-I.A.` — ambos funcionaram sem erro de autenticação). Ou seja, dá para trabalhar com o GitHub via git/CLI mesmo com o conector MCP bloqueado; só recursos que dependem especificamente do conector (ex.: abrir PR pela API, comentar issues) ficam indisponíveis até a Tatiana resolver a ADR-pendente-06.
- **Anthropic**: usado diretamente (SDK) em dois lugares (TS e Python), sem abstração.
- **Resend**: usado para envio de email em `Projeto ClaudeCode` e em skills de `ssw-relatorios` — coexiste com o Email Agent oficial, o que já é uma divergência conhecida (não fechada) documentada em memória.
- **n8n, Manus, Gemini, OpenAI/ChatGPT API**: nenhuma integração técnica encontrada em código. São 100% novos para este projeto.

## 4. Componentes reutilizáveis

- **`ssw-relatorios\.claude\hooks\pre_tool_check.ps1`** — padrão de gating por whitelist/blacklist de comando, adaptável para o `Security Layer`/modos `READ_ONLY/ASSISTED/AUTONOMOUS` do orchestrator (FASE 7 do PRP-003). É a peça de "prior art" mais próxima do que o PRP pede.
- **Schema do Supabase `pendency-tracker`** — contém exatamente o tipo de tabela que a FASE 8 (Evidence-First) e FASE 11 (entidades Supabase) do PRP-003 pedem, só que já em produção:
  - `integration_action_audit`, `integration_ingestion_audit` — audit log de ações/ingestões por integração.
  - `email_rule_execution_log` — log de execução de regra automatizada, com resultado.
  - `email_learning_rules` — **separa `platform_action` de `gmail_action`**, e a ação real (`gmail_action`) só executa porque a regra foi aprovada explicitamente na criação. Isso é literalmente o padrão de "ação automática vs. aprovação humana" que a FASE 7/9 do PRP-003 pede, já validado em produção.
  - `ai_suggestions` (761 linhas) — já existe uma tabela de sugestões geradas por IA nesse banco.
  - `email_audit_log`, `oauth_states` — padrões adicionais de auditoria/segurança.
- **Email Agent (`ia.sal@salexpress.com.br`)** — canal oficial único de notificação; o Orchestrator deve usá-lo para qualquer output de alerta/notificação em vez de reimplementar envio.
- **6 skills de `ssw-relatorios\.claude\skills\`** — não são routing engine, mas são exemplos reais de "skill" com estrutura própria (a `auditor-independente`, em particular, é só leitura/diagnóstico — modelo direto para as convenções de `skills/` da FASE 6 do PRP-003).
- **Convenção de segredos** — `.env` + `.gitignore` é consistente nos 3 projetos locais (embora só um deles seja de fato um repo git). Nenhum segredo será copiado; só o padrão é reaproveitável.

## 5. Conflitos

- **Duplicidade de clone**: `C:\ssw-relatorios` e `C:\Projeto ClaudeCode\Github\Devolucao-031-emissao` são dois clones locais do **mesmo** repositório GitHub (`tatiana-kelly/Devolucao-031-emissao`). `ssw-relatorios` tem 5 commits locais não empurrados + mudanças não commitadas; o clone dentro de `Projeto ClaudeCode` está limpo/atualizado. Isso não bloqueia o PRP-003 diretamente, mas é risco lateral: se o orchestrator vier a interagir com esse pipeline, precisa saber qual cópia é a fonte da verdade (recomendação: `ssw-relatorios`, por ter o trabalho mais recente).
- **Dois mecanismos concorrentes de envio de email** (Email Agent oficial vs. Resend usado em `Projeto ClaudeCode` e nas skills de `ssw-relatorios`) — decisão de descontinuar o não-oficial já está registrada como pendente em memória, não é bloqueio novo, só reforça que o Orchestrator não deve introduzir um terceiro mecanismo.
- **Nome do repositório com ponto final** (`AGENTE-I.A.`) causa erro no Windows ao tentar criar uma pasta local com o mesmo nome (`Invalid argument` — Windows não aceita diretório terminado em ponto). Não é um conflito de dados, é uma armadilha operacional: qualquer clone local precisa usar um nome de pasta ligeiramente diferente (usei `AGENTE-I.A` sem o ponto final).

## 6. Gaps

- **n8n**: nenhuma evidência local. Sem isso, a FASE 13 (integração com n8n: `POST /orchestrate`, `GET /tasks/:id`, `POST /tasks/:id/continue`) pode ser implementada do lado do Orchestrator, mas não pode ser *validada* ponta a ponta até localizar/confirmar onde o n8n roda.
- **Manus**: nenhuma conta, API key ou integração existente — FASE 14 é 100% nova, inclusive a etapa de descobrir a documentação oficial atual da API do Manus (a instrução do PRP pede explicitamente "não usar API deprecated" — isso exige checar a doc oficial no momento da implementação, não algo que dá pra confirmar só com Discovery local).
- **GitHub via MCP**: conector segue bloqueado (ADR-pendente-06). Mitigado para esta sessão via git CLI local, mas funcionalidades que dependem da API do GitHub (criar PR, comentar, Actions via API) não são exercitáveis pelo MCP até a Tatiana resolver a conexão do conector certo.
- **Provider abstraction**: não existe nada para reaproveitar — é greenfield real, meses de trabalho em 3 projetos diferentes e nenhum deles criou uma interface `AIProvider`.
- **Cost tracking**: não existe em nenhum lugar. Nenhuma métrica de custo de IA está sendo capturada hoje.
- **Servidor Ubuntu 192.168.100.37**: mencionado em investigação anterior como não acessado — pode ser onde n8n vive, mas não foi possível confirmar nesta sessão (sem acesso de rede/SSH).

## 7. Arquivos protegidos

- **`C:\SAL_AI_OS\`** inteiro — é Control Plane de governança, não deve receber código de produção nem ser tratado como o repositório do Orchestrator.
- **`salexpress-ai`** (projeto Lovable, mencionado em memória) — de outro responsável (Caio), marcado "NÃO MEXA". Fora de escopo do PRP-003.
- **`integrations/service_account.json`** dentro de `CENTRO-DE-AGENTES-IA` — credencial real em disco, não deve ser lida/copiada/movida.
- **Qualquer `.env` real** nos três projetos locais (`ssw-relatorios\.env`, `Projeto ClaudeCode\.env`, etc.) — valores não foram lidos nesta Discovery e não devem ser copiados para o novo repositório.
- **`ssw-relatorios`** com mudanças não commitadas e commits não empurrados — não deve ser tocado/alterado como efeito colateral do trabalho do Orchestrator.
- Regra geral herdada do Control Plane: nenhuma estrutura existente (Lovable, Supabase, automações locais) deve ser movida, renomeada ou alterada como parte da implementação do PRP-003.

## 8. Arquivos que deverão ser criados

Estrutura mínima da FASE 1-22 do PRP-003, a partir do zero em `C:\Users\tatiana.silva\AGENTE-I.A` (clone local do repo vazio `github.com/tatiana-kelly/AGENTE-I.A.`):

```
AGENTE-I.A/
  README.md
  CLAUDE.md
  .env.example
  .gitignore
  src/
    orchestrator/          (Task Classifier, Context Resolver, Routing Engine,
                             Task Planner, Provider Manager, Validation Engine,
                             Evidence Manager, Cost Controller, Security Layer,
                             Observability)
    providers/              (interface AIProvider + openai/manus/anthropic/gemini)
    routing/                (matriz configurável por skill/domínio)
  projects/<project>/       (PROJECT-CONTEXT.md, DATA-DICTIONARY.md, etc. — FASE 5)
  skills/                   (FASE 6, cada skill com SKILL.md/ROUTING.md/VALIDATION.md)
  docs/                     (architecture.md, routing.md, providers.md, skills.md,
                             security.md, context.md, n8n.md, mcp.md, development.md)
  tests/                    (routing tests — FASE 18)
```

Este `DISCOVERY-REPORT.md` já foi criado (este arquivo). Nenhum outro arquivo acima foi criado ainda.

## 9. Arquitetura recomendada

A arquitetura oficial do PRP-003 (n8n → AI Orchestrator → providers → Claude Code constrói → Supabase/GitHub/Vercel) **não precisa de nenhuma alteração** — é compatível com tudo que foi encontrado:

- O Orchestrator deve ser um **repositório novo e independente** (`AGENTE-I.A.`), não uma pasta dentro de `C:\SAL_AI_OS\` (que é só governança) nem dentro de `Projeto ClaudeCode`/`ssw-relatorios` (que são pipelines de domínio específico).
- **Reaproveitar o schema de evidence/audit de `pendency-tracker`** como ponto de partida conceitual para as tabelas `ai_tasks`/`ai_runs`/`ai_routing_decisions`/etc. da FASE 11, em vez de desenhar do zero — o padrão `platform_action` vs. `gmail_action` com aprovação explícita já resolve boa parte do requisito de FASE 7/9.
- **Reaproveitar o hook `pre_tool_check.ps1`** como referência de design para o Security Layer/modos de execução, adaptado para o contexto do Orchestrator (que não é um hook de Claude Code, mas pode usar a mesma lógica de whitelist/blacklist).
- **Roteirizar todo envio de notificação através do Email Agent oficial**, nunca via Resend direto.
- Trabalhar com o GitHub via **git CLI local** enquanto o conector MCP não for resolvido, documentando isso como decisão temporária no `DECISION_LOG.md` do Control Plane (não duplicar a governança — só referenciar).

## 10. Riscos

1. **GitHub MCP indisponível** — não bloqueia o desenvolvimento (git CLI funciona), mas bloqueia qualquer automação futura que dependa da API do GitHub via este ambiente até a ADR-pendente-06 ser resolvida pela Tatiana.
2. **n8n não localizado** — risco de construir a integração (FASE 13) sem poder validá-la ponta a ponta.
3. **Manus API** — risco de implementar contra documentação desatualizada se não for verificada a doc oficial no momento da FASE 14 (o próprio PRP pede isso explicitamente).
4. **Escopo muito grande (22 fases)** — risco de um único ciclo de implementação tentar entregar tudo de uma vez, violando a própria regra do PRP de "commits pequenos" e o princípio do Control Plane de mudança incremental e reversível. Recomendação: tratar cada Fase como PR pequeno e independente, não uma entrega única.
5. **Duplicação de mecanismos** (email, agentes) se o Orchestrator não checar antes de criar — mitigado seguindo a "Regra de ouro" do Control Plane (`ALREADY_EXISTS.md` → REUSE/EXTEND/CREATE).
6. **Nome do repo com ponto final** — pode causar problemas em ferramentas/scripts que assumem nomes de pasta = nome de repo (Windows não aceita `AGENTE-I.A.` como nome de diretório). Recomendação: usar `AGENTE-I.A` (sem ponto) como convenção de pasta local em qualquer máquina Windows que clonar este repo, documentado no README.
7. **Cadeia de comando**: este PRP-003 chegou como instrução direta e detalhada da Tatiana (via arquivo anexado), incluindo arquitetura já definida como "NÃO ALTERAR". Isso é consistente com a cadeia de comando do Control Plane (Tatiana aprova, ChatGPT decide arquitetura, Claude Code executa) — não há conflito, mas qualquer desvio da arquitetura descrita no PRP-003 durante a implementação deve voltar para decisão, não ser resolvido unilateralmente.

---

**Próximo passo:** apresentar este relatório à Tatiana e aguardar autorização explícita para iniciar a FASE 1 (CORE) — nada será implementado, commitado ou enviado ao GitHub antes dessa confirmação, conforme REGRA ZERO do PRP-003.
