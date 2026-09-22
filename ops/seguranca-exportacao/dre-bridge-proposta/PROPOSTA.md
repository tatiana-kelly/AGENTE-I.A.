# PROPOSTA: dre-bridge sem push automático

`C:\Projeto ClaudeCode\dre-bridge` **não é um repositório git**. Por isso não mexi no arquivo em uso.
O `LEIA-ME - fonte de verdade.txt` diz que a fonte de verdade é `tati-command-deck/scripts/dre-bridge/`,
mas esse caminho local não existe mais nesta máquina.

## Como funciona hoje (`baixar_dres_local.py`)
- `main()` baixa os DREs da Edge Function `dre-export` para `C:\Projeto ClaudeCode\DRE\AAAA-MM` (l.167-225)
  e copia para `C:\DRE - Demonstrativo de Resultado` sem sobrescrever os arquivos que você já tinha (l.131-153).
- No fim, chama `publicar_no_git(escritos)` (l.245). Se `C:\DRE - Demonstrativo de Resultado\.git` existir
  (e existe, com remoto `tatiana-kelly/DRE`), ela checa se o repositório está privado (l.62-76), roda `git add`
  só nos arquivos baixados, `git commit` (l.99-112) e **`git push origin HEAD` (l.113)**. Tudo isso roda
  sozinho às 10:00, pela tarefa agendada que usa pythonw.exe.

## O que muda (só em `publicar_no_git`; download e cópia continuam iguais)
- Por padrão faz só o **commit local** e registra
  `[GIT] Commit LOCAL feito (...). PUSH PENDENTE DE APROVACAO -- nada foi enviado ao GitHub. Commits aguardando push: N`.
- O push só acontece com `DRE_BRIDGE_ALLOW_PUSH=1` (tem que ser exatamente `1`). Mesmo com a variável ligada,
  a trava que exige repositório privado continua valendo. Se não der para confirmar que está privado, o push não é feito.
- Todas as mensagens `[GIT]` também vão para `git_publicacao.log`, na mesma pasta do script. Sob pythonw.exe
  não existe console, então sem esse arquivo o aviso de push pendente se perderia. O caminho pode ser trocado
  com `DRE_BRIDGE_LOG_GIT`.
- No modo padrão a rotina não acessa mais a internet para o git. A checagem no GitHub só roda quando o push foi autorizado.

## Arquivos
- `baixar_dres_local.patch`: diff unificado (CRLF, como o original), testado com `patch --dry-run` contra o arquivo em uso.
  **Use este para aplicar.**
- `baixar_dres_local.py`: versão completa já com a mudança, só para leitura e teste. A chave `SOURCE_ANON`
  está **REDIGIDA**, então não copie este arquivo por cima do original.
- `tests/test_push_aprovacao.py`: 5 testes (unittest, com git e rede simulados). Resultado: OK.
  Rodar com `python -m unittest discover -s tests`. Para testar o script em uso, defina `DRE_BRIDGE_SCRIPT=<caminho>`.

## Para aplicar (precisa da sua aprovação)
    cd "C:\Projeto ClaudeCode\dre-bridge"
    copy baixar_dres_local.py baixar_dres_local.py.bak
    # no Git Bash (mesma forma validada com --dry-run):
    patch --binary -p1 baixar_dres_local.py < "<esta pasta>/baixar_dres_local.patch"

Depois disso, versione o script onde ficar a nova fonte de verdade.

## Pendente para você decidir
1. Aplicar ou não o patch no script em uso. A tarefa agendada **não** precisa mudar.
2. Quando publicar: revise os commits locais e rode `git -C "C:\DRE - Demonstrativo de Resultado" push`,
   ou rode uma única vez à mão com `DRE_BRIDGE_ALLOW_PUSH=1`. **Não** coloque essa variável na tarefa agendada.
3. Enquanto ninguém fizer o push, os commits locais vão se acumulando. Um push depois envia todos de uma vez.
