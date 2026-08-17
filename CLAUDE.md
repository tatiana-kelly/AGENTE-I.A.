# CLAUDE.md — AGENTE-I.A. (SAL AI OS / AI Orchestrator)

Regras para qualquer agente (Claude Code ou outro) que trabalhar neste repositório.

## O que é este repositório

Implementação do PRP-003: a camada central de orquestração de IA do SAL AI OS. Ver [README.md](README.md) para arquitetura e status, e [DISCOVERY-REPORT.md](DISCOVERY-REPORT.md) para o levantamento que precedeu a implementação.

## Arquitetura — NÃO ALTERAR

```
n8n = quando/como executar
AI Orchestrator (este repo) = qual IA deve pensar/executar
ChatGPT/OpenAI = decide
Manus = investiga/faz
Claude Code = constrói
Gemini = ecossistema Google
Supabase = dados
GitHub = código
Vercel = deploy
```

Qualquer desvio dessa divisão de responsabilidades durante a implementação volta para decisão da Tatiana/ChatGPT — não é resolvido unilateralmente pelo Claude Code.

## Cadeia de comando

```
TATIANA (negócio, prioridade, aprovação)
   ↓
CHATGPT (arquitetura, PRPs, decisões estruturais)
   ↓
CLAUDE CODE (execução, código, testes)
```

Decisão estrutural nova → não decidir sozinho. Este repo não duplica a governança do Control Plane (`C:\SAL_AI_OS\`); se uma decisão precisar ser registrada, referenciar `C:\SAL_AI_OS\00_GOVERNANCA\DECISION_LOG.md`, não recriar um decision log aqui.

## Regras de segurança (FASE 7 e FASE 15)

- Modo default do orchestrator: `READ_ONLY`, `DRY_RUN=true` (ver `.env.example` e `src/orchestrator/securityLayer.ts`).
- Nunca commitar `.env` real, chaves de API, tokens ou credenciais — só `.env.example` com placeholders.
- Nunca enfraquecer o gate de segurança (`evaluateExecution`) sem autorização explícita e registrada.
- **Push para o GitHub remoto requer autorização explícita a cada vez** — uma autorização não vale para a sessão inteira nem para sessões futuras. Commits locais podem ser feitos livremente durante o desenvolvimento.
- Conector MCP do GitHub pode estar indisponível (ver DISCOVERY-REPORT.md, seção 3) — usar `git` via linha de comando funciona normalmente com as credenciais já configuradas na máquina.

## Convenções de commit (FASE 22)

Commits pequenos, um por módulo/funcionalidade, no padrão `tipo(escopo): descrição` (ex.: `feat(router): add task classifier`, `test(router): add routing tests`). Nunca um commit gigante cobrindo várias fases.

## Regra de ouro (herdada do Control Plane)

Antes de criar qualquer coisa nova — provider, skill, tabela, integração — checar se já existe algo reaproveitável:

```
NECESSIDADE → já existe (ver DISCOVERY-REPORT.md / C:\SAL_AI_OS\ALREADY_EXISTS.md) → REUSE / EXTEND / CREATE
```

Reaproveitamento já identificado nesta Discovery (não redesenhar):

- **Persistência do Orchestrator**: a FASE 11 pertence exclusivamente a este projeto. Não acessar, reutilizar nem alterar o schema do `pendency-tracker`, que é outro produto e está fora de escopo por decisão da Tatiana em 2026-08-17.
- **Gating de execução**: `C:\ssw-relatorios\.claude\hooks\pre_tool_check.ps1` — inspirou `src/orchestrator/securityLayer.ts`.
- **Email**: qualquer notificação sai pelo Email Agent oficial (`ia.sal@salexpress.com.br`) — nunca reimplementar envio direto (Resend, SMTP, etc.).

## Comandos

```bash
npm install       # instalar dependências
npm run typecheck # tsc --noEmit
npm test          # vitest run
npm run build     # tsc -p tsconfig.json
```

## Arquivos/diretórios protegidos

- `C:\SAL_AI_OS\` — Control Plane de governança de outro repositório; nunca receber código de produção.
- `salexpress-ai` (Lovable, outro responsável) — fora de escopo, "NÃO MEXA".
- Qualquer `.env` real, `integrations/service_account.json` ou credencial em disco fora deste repo — nunca ler, copiar ou commitar.
- Nada fora deste repositório deve ser alterado como efeito colateral do trabalho aqui (ver DISCOVERY-REPORT.md, seção 7, para a lista completa levantada na Discovery).

## Testes

`tests/routing.test.ts` cobre os exemplos de routing da FASE 18 do PRP-003 e o exemplo citado em "Definição de Sucesso". Qualquer mudança na matriz de roteamento (`routingEngine.ts`) ou no planner (`taskPlanner.ts`) deve manter esses testes passando ou atualizá-los deliberadamente, nunca deixá-los quebrados.
