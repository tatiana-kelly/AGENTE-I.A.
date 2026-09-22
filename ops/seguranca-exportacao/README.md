# Segurança das exportações de DRE e faturamento

Correção de um risco real encontrado em 2026-09-19: as Edge Functions `dre-export` e `faturamento-export`
(projeto Supabase da Plataforma de Produtividade, `isxmcpobhzzhwfnaozsr`) aceitavam a **chave pública (anon)**
e não conferiam quem chamava. Na prática, quem tivesse essa chave — que está no bundle do site e em vários
scripts — conseguia ler **todos os DREs**, o **HTML do faturamento** e, pelo `gmail_message_id`,
**qualquer e-mail da caixa**.

## O que foi corrigido (código nas branches, nada publicado)

| Onde | Branch | O que mudou |
|---|---|---|
| Produtividade (`tati-command-deck`) | `fix/export-auth` | Segredo próprio por consumidor no header `x-export-secret`, comparado em tempo constante; sem segredo configurado, a função bloqueia (503); o faturamento só devolve o relatório oficial (remetente + assunto), e qualquer outra mensagem vira 404 |
| Torre de Controle | `fix/export-secret-header` | `snapshot/faturamento_client.py` envia `FATURAMENTO_EXPORT_SECRET` (lido do `.env` da Torre) |
| Produtividade (scripts do DRE) | `fix/export-auth` | `scripts/dre-bridge/*.py` enviam `EXPORT_SECRET_DRE_LOCAL` |
| `C:\Projeto ClaudeCode\dre-bridge` (não é repositório git) | — | `dre-bridge-proposta/baixar_dres_local.export-secret.patch` (header do segredo) e `baixar_dres_local.patch` (tira o push automático; ver `PROPOSTA.md`) |
| dp-vision-board | — | precisa enviar o header com `EXPORT_SECRET_DPVISION`; a função vive no Lovable Cloud |

Testes: 16 no módulo de autenticação e na trava do faturamento (`npm run test:export-auth` na branch).

## Como implantar

`implantar-segredos-exportacao.ps1`, uma fase por vez. Os segredos são gerados na máquina da Tatiana e
gravados direto no destino: **nunca aparecem na tela e nunca passam pelo Claude**.

```powershell
supabase login
powershell -ExecutionPolicy Bypass -File .\implantar-segredos-exportacao.ps1 -Fase 1
```

| Fase | O que faz | Quebra algo? |
|---|---|---|
| 1 | Cria os 3 segredos, grava no Supabase, no `.env` da Torre e na variável de usuário do Windows; liga a transição; copia o segredo do dp-vision para a área de transferência | não |
| — | No Lovable do dp-vision: criar `EXPORT_SECRET_DPVISION` e enviar o header em `importar-dres` | não |
| 2 | Publica as 2 funções (a partir de um checkout da branch `fix/export-auth`) | não |
| 3 | Aplica os ajustes na Torre (cherry-pick) e no dre-bridge (patch com backup) | não |
| 4 | Desliga a transição: sem segredo, ninguém passa | sim, se algum consumidor ficou sem o segredo |
| 5 | Confere que a chave pública sozinha recebe 401 | — |

Volta atrás imediata, se a fase 4 quebrar algo:

```powershell
supabase secrets set --project-ref isxmcpobhzzhwfnaozsr EXPORT_ALLOW_LEGACY_ANON=true
```

## Pendente

- Publicar as branches (push e merge) depois da implantação.
- Trocar a chave anon que está gravada em scripts e documentos, se você quiser rotacioná-la.
