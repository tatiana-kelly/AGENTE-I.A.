# Torre de Controle — Arquitetura resumida

snapshot/ (Python, roda local com credenciais): motor_snapshot_painel.py orquestra ·
config_operacional.py (capacidades, faixas, alertas) · config_lanes.py · config_unidades.py ·
cargo_dispatch_client.py (fotos/ocupação visual, Fase 2) · scripts de auditoria
(auditar_divergencia_bi_torre.py, auditar_total_transf_bi_vs_torre.py, validar_os_coleta.py).

src/ (Next.js 14, SSG puro — `force-static`): app/page.tsx monta a sequência de blocos ·
components/ (main-view, custo-composicao, deviation-panel, daily-table, performance-action,
operational-diagnostic [drill-down com abas Transferências/Custo×Performance/Clientes-âncora/
Alertas], data-health, source-status, cargo-photos-recent) · lib/ (types, format, metas,
diagnostic, data).

data/YYYY-MM.json + latest.json = único insumo do frontend, consumido em build-time.
docs/regras-negocio/ é a fonte da verdade das regras; docs/GOVERNANCA_ALTA_GESTAO_CONTROLE.md
registra a separação Alta Gestão × Controle e as decisões da Tatiana.

## Onde cada diretório vive (importante para qualquer agente)

| Diretório | Branch | Papel |
|---|---|---|
| `C:\Projeto ClaudeCode\Torre-de-Controle` | `main` | **OPERAÇÃO.** As tarefas agendadas rodam aqui, commitam `data/` e fazem `git push origin main` sozinhas. Não escrever código novo nem commitar aqui. |
| `C:\Projeto ClaudeCode\Torre-claude` | `dev/claude` | **Worktree de código.** É aqui que o agente escreve e commita. Merge em `main` só com o "sim" da Tatiana. |
| `C:\Projeto ClaudeCode\Torre-fechamento` | `feature/fechamento-agosto-setembro` | Worktree do fechamento mensal. |

Cada worktree tem o seu próprio HEAD — é essa separação física que impede um commit de
código de pegar carona no `git push` automático da rodada. Abrir branch no diretório da
operação NÃO resolve: as tarefas commitam na branch que estiver ativa.

Nunca usar `git commit --amend`, `rebase -i` ou `reset --hard` no diretório da operação:
uma rodada pode ter commitado no meio, e o comando reescreve o commit dela.

Automação: `.github/workflows/operacao-diaria.yml` e `rodada-macro-17h.yml` (nuvem) +
`snapshot/*.bat` agendados no Windows (local). Todos usam `git add data\` — escopo restrito,
nunca `git add -A`.
