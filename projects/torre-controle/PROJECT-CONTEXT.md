# Torre de Controle — SAL Express (contexto do projeto)

Painel diário Faturamento × Custos da SAL Express. Repo
github.com/tatiana-kelly/Torre-de-Controle- (local C:\Projeto ClaudeCode\Torre-de-Controle),
Next.js 14 gerado 100% estático (SSG), deploy Vercel. NÃO tem backend, login nem banco de escrita.

Fluxo de atualização (automatizado, várias rodadas por dia): `snapshot/motor_snapshot_painel.py`
roda LOCALMENTE, consolida as fontes, gera `data/YYYY-MM.json`; os `.bat` agendados fazem
`git add data\` + `git commit` + `git push origin main` sozinhos, e a Vercel regenera o site.
Regra de ouro: credenciais Power BI e Supabase NUNCA vão para o repositório — ficam só na
máquina que roda o snapshot. A Vercel serve apenas o JSON já processado.

Fontes: BI Farol (faturamento), BI Custo Transferência/Paratus, BI Custo Coleta, BI Custo
Entrega, Supabase 455 (Motor v3.2 de Parceiros, 35 siglas F1-F6).

Decisão de governança aprovada em 17/08/2026 (docs/GOVERNANCA_ALTA_GESTAO_CONTROLE.md):
separar a plataforma em ALTA GESTÃO (diretoria/heads — consolidado, nunca prescritivo por
item) e CONTROLE (equipe operacional — granular + confirma/rejeita as recomendações do motor).
Dono da revisão: Bruno Lacerda. SLA: 48h úteis. Prioridade: fila normal.
