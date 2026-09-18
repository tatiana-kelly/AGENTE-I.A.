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

1. `C:\Users\tatiana.silva\.claude\skills\integrar-email-agent\SKILL.md` contém o **valor literal** do
   segredo compartilhado `EMAIL_AGENT_TRIGGER_SECRET`. Recomendação: remover o valor do arquivo e rotacionar
   o segredo nos projetos Supabase que o usam.
2. `C:\ssw-relatorios\enviar_resumo_455.py` envia e-mail via **Resend direto** (remetente `onboarding@resend.dev`),
   fora do Email Agent oficial — candidato a migração com a skill `integrar-email-agent`.
3. `.env` e backups `.env.bak-*` em `C:\ssw-relatorios`, `C:\Projeto ClaudeCode`, `tati-command-deck` — confirmar
   que estão no `.gitignore` dos respectivos repositórios.
