# Segurança

- **Nenhum segredo em código, registry, Skill ou config.** Credenciais só via ambiente (`{env:NOME}`); o validador
  do registry rejeita valor literal com cara de segredo (teste `test_rejects_invalid`).
- **Redação automática** (`redact.py`) em tudo que vai para memória, auditoria, outbox e notificação:
  `chave=valor` de api_key/token/secret/senha, `Bearer`, `sk-…`, `ghp_…`, JWT, AWS, DSN postgres.
- **Arquivos proibidos nunca são lidos**: `.env`, `auth.json`, credenciais, `.pem/.key` (a auditoria só registrou existência).
- **DRY_RUN=true por padrão.** Execução real exige `dry_run=false` **e** `autonomous_repair=true`.
- **Matriz de permissões + registry**: ação precisa estar em `allowed_recovery_actions`, ser de risco baixo e a
  automação `idempotent: true`. Automações que enviam e-mail/WhatsApp estão com reexecução bloqueada.
- **Circuit breaker, rate limits, janela de reparo, chave de idempotência por tentativa**: sem loops.
- **Canais externos desligados** até decisão explícita (`notification.external_enabled`).
- **Supply chain**: zero dependências de terceiros.

## Achados de segurança da auditoria (fora do escopo deste código — requer decisão da Tatiana)

1. `EMAIL_AGENT_TRIGGER_SECRET` — removido da skill em 18/09/2026. A auditoria da Fase 2 encontrou o **mesmo valor**
   literal em 6 funções SQL de produção (`relatorios-raw` ×1, `Gente & Gestao` ×5), no histórico do repo privado
   `tatiana-kelly/sousaleisamar` (commit `8ed2b47`) e em 12 transcripts locais. **Rotação: HUMAN_REQUIRED (bloqueador)**,
   com passos e locais em `hardening-phase2.md` §A.
2. `C:\ssw-relatorios\enviar_resumo_455.py` enviava via **Resend direto** — **corrigido em 18/09/2026** para o Email Agent
   (working tree, sem commit). Pendente: envio real de teste autorizado e remoção de `RESEND_API_KEY` do `.env`.
3. `.env` e backups `.env.bak-*` em `C:\ssw-relatorios`, `C:\Projeto ClaudeCode`, `tati-command-deck` — confirmar
   que estão no `.gitignore` dos respectivos repositórios.
