# -*- coding: utf-8 -*-
"""
Baixa os DREs do Supabase da Plataforma para pastas locais no computador.

DOIS DESTINOS (pedido dela em 25/08/2026: "vc precisa incluir todas aqui tbm
nesta pasta C:\\DRE - Demonstrativo de Resultado"):

  1. ESPELHO TECNICO  C:\\Projeto ClaudeCode\\DRE\\AAAA-MM\\<id>_arquivo
     Mesma organizacao do Supabase e do dp-vision-board (mes do E-MAIL, nao da
     competencia). O prefixo <id> e o id da mensagem do Gmail — garante que
     dois anexos de nome igual, vindos de e-mails diferentes, nunca colidam.

  2. PASTA DE TRABALHO DELA  C:\\DRE - Demonstrativo de Resultado\\arquivo
     Plana, com o nome limpo do anexo (do jeito que ela ja usava).

REGRA DE OURO NESTA PASTA 2: nunca sobrescrever arquivo dela.
Ela ja mantinha copias proprias ali e 4 de 6 tinham o MESMO NOME mas conteudo
DIFERENTE do anexo original (provavelmente versoes trabalhadas por ela). Se o
nome ja existe:
  - conteudo identico  -> nao faz nada;
  - conteudo diferente -> grava a versao do e-mail com sufixo
    " (e-mail AAAA-MM-DD)" e deixa a dela intacta.

Rodar:  python baixar_dres_local.py
Idempotente: pula o que ja existe com o mesmo tamanho.
Variaveis opcionais: DRE_DEST (espelho tecnico) e DRE_DEST_TRABALHO.

PUSH SO COM APROVACAO (19/09/2026): por padrao a rotina faz so o commit LOCAL
dos DREs baixados e registra "push pendente de aprovacao" em
git_publicacao.log (ao lado do script). O push para o GitHub so acontece com
DRE_BRIDGE_ALLOW_PUSH=1 -- desligado por padrao, e nao deve ser ligado na
tarefa agendada: push exige aprovacao humana explicita a cada vez.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _export_secret_header():
    """Segredo próprio deste consumidor no dre-export (EXPORT_SECRET_DRE_LOCAL). Nunca logado."""
    secret = os.environ.get("EXPORT_SECRET_DRE_LOCAL", "").strip()
    if not secret:
        print("[AVISO] EXPORT_SECRET_DRE_LOCAL ausente: o dre-export vai recusar depois da transição", flush=True)
        return {}
    return {"x-export-secret": secret}

SOURCE_URL = "https://isxmcpobhzzhwfnaozsr.supabase.co"
SOURCE_ANON = "<REDIGIDO - manter o valor do script original>"

DEST = Path(os.environ.get("DRE_DEST", r"C:\Projeto ClaudeCode\DRE"))
DEST_TRABALHO = Path(os.environ.get("DRE_DEST_TRABALHO",
                                    r"C:\DRE - Demonstrativo de Resultado"))


VAR_PUSH = "DRE_BRIDGE_ALLOW_PUSH"
LOG_GIT = Path(os.environ.get(
    "DRE_BRIDGE_LOG_GIT", str(Path(__file__).resolve().parent / "git_publicacao.log")))


def push_autorizado(ambiente=None):
    """Push so com DRE_BRIDGE_ALLOW_PUSH=1 (exatamente "1"). Padrao: desligado."""
    ambiente = os.environ if ambiente is None else ambiente
    return (ambiente.get(VAR_PUSH) or "").strip() == "1"


def registrar_git(mensagem):
    """print + arquivo: a tarefa agendada roda com pythonw.exe, que nao tem
    console -- sem o arquivo, o aviso de push pendente se perderia."""
    print(mensagem)
    try:
        with open(LOG_GIT, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), mensagem))
    except OSError:
        pass


def _repositorio_esta_publico():
    """True/False/None (None = nao deu para saber -> tratar como inseguro).

    TRAVA DE SEGURANCA (25/08/2026): DRE e dado financeiro confidencial. Se a
    API publica do GitHub responde 200, qualquer um consegue ler o repositorio
    -- um push ali exporia faturamento, custo e margem da empresa, e o
    historico do git guardaria copia mesmo depois de apagar."""
    try:
        with urllib.request.urlopen(
                "https://api.github.com/repos/tatiana-kelly/DRE", timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:  # 404 = privado (ou inexistente) = seguro seguir
            return False
        registrar_git(f"[GIT] Nao consegui checar a visibilidade ({e.code}).")
        return None
    except Exception as e:
        registrar_git(f"[GIT] Nao consegui checar a visibilidade ({str(e)[:60]}).")
        return None


def publicar_no_git(arquivos=()):
    """Commita LOCALMENTE no repositorio da pasta de trabalho (remoto
    tatiana-kelly/DRE) SOMENTE os DREs que esta execucao escreveu.

    PUSH (19/09/2026): antes esta funcao fazia `git push` sozinha, todo dia,
    sem ninguem aprovar. Regra da empresa: push exige aprovacao humana
    explicita. Agora o padrao e so o commit local + registro de "push
    pendente de aprovacao"; o push so roda com DRE_BRIDGE_ALLOW_PUSH=1 e,
    mesmo assim, so depois da trava de visibilidade (repositorio privado)."""
    import subprocess
    if not (DEST_TRABALHO / ".git").exists():
        return  # pasta ainda nao e repositorio: nada a publicar

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(DEST_TRABALHO),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)

    # ESCOPO (03/09/2026): aqui havia um `git add -A`, que leva tudo que
    # estiver no working tree. Nesse dia a tarefa publicou 33 arquivos de
    # codigo em andamento junto com os DREs, sem ninguem pedir -- e a
    # mensagem ainda dizia "(0 arquivo(s))". O escopo do commit tem de ser
    # o escopo da tarefa: os anexos que ela acabou de baixar, e nada mais.
    relativos = []
    for caminho in arquivos:
        try:
            relativos.append(str(Path(caminho).resolve().relative_to(
                DEST_TRABALHO.resolve())))
        except ValueError:
            continue      # fora da pasta de trabalho: nao e nosso para publicar
    if not relativos:
        registrar_git("[GIT] Nada novo para commitar.")
        return

    git("add", "--", *relativos)
    # A contagem sai do que REALMENTE foi para o index. O
    # `git status --porcelain --cached` de antes devolvia vazio, e por isso
    # o log dizia zero enquanto o commit levava trinta e tres.
    n = len([l for l in git("diff", "--cached", "--name-only").stdout.splitlines()
             if l.strip()])
    if n == 0:
        registrar_git("[GIT] Os DREs baixados ja estavam commitados.")
        return
    hoje = time.strftime("%d/%m/%Y")
    r = git("commit", "-m", f"DRE: sincronizacao automatica {hoje} ({n} arquivo(s))")
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        registrar_git(f"[GIT] Falha no commit: {(r.stderr or r.stdout)[:200]}")
        return

    if not push_autorizado():
        # Conta local (sem rede) dos commits que ainda nao foram ao remoto.
        r = git("rev-list", "--count", "@{u}..HEAD")
        fila = r.stdout.strip() if r.returncode == 0 else "?"
        registrar_git(
            f"[GIT] Commit LOCAL feito ({n} arquivo(s)). PUSH PENDENTE DE APROVACAO "
            f"-- nada foi enviado ao GitHub. Commits aguardando push: {fila}. "
            f"Para publicar, com aprovacao: git -C \"{DEST_TRABALHO}\" push "
            f"(ou rodar uma vez com {VAR_PUSH}=1).")
        return

    publico = _repositorio_esta_publico()
    if publico is None:
        registrar_git("[GIT] Push NAO feito por seguranca (visibilidade desconhecida). "
                      "Commit local mantido.")
        return
    if publico:
        registrar_git("[GIT] Push ABORTADO: o repositorio tatiana-kelly/DRE esta PUBLICO. "
                      "DRE e confidencial. Settings > General > Danger Zone > "
                      "Change visibility > Make private. Commit local mantido.")
        return
    r = git("push", "origin", "HEAD")
    if r.returncode == 0:
        registrar_git(f"[GIT] Publicado no GitHub ({n} arquivo(s)) com {VAR_PUSH}=1.")
    else:
        registrar_git(f"[GIT] Commit feito, PUSH falhou: {(r.stderr or r.stdout)[:200]}")


def nome_limpo(storage_path):
    """"2026-08/1a0343c99dd7913a_DRE Julho.xlsx" -> "DRE Julho.xlsx"
    (o prefixo e o id da mensagem do Gmail, so serve para o espelho tecnico)."""
    nome = Path(storage_path).name
    if "_" in nome:
        pref, resto = nome.split("_", 1)
        if len(pref) == 16 and all(c in "0123456789abcdef" for c in pref.lower()):
            return resto
    return nome


def copiar_para_pasta_trabalho(origem: Path, doc):
    """Copia para a pasta dela SEM NUNCA sobrescrever arquivo dela.

    Devolve (desfecho, caminho). O caminho passou a ser devolvido para o
    commit poder somar EXATAMENTE o que esta execucao escreveu -- ver
    publicar_no_git."""
    DEST_TRABALHO.mkdir(parents=True, exist_ok=True)
    alvo = DEST_TRABALHO / nome_limpo(doc["storage_path"])
    dados = origem.read_bytes()

    if alvo.exists():
        if alvo.stat().st_size == len(dados) and alvo.read_bytes() == dados:
            return "ja_igual", alvo
        # mesmo nome, conteudo diferente: a dela manda, a do e-mail ganha sufixo
        data = (doc.get("received_at") or "")[:10] or "sem-data"
        alvo = alvo.with_name(f"{alvo.stem} (e-mail {data}){alvo.suffix}")
        if alvo.exists() and alvo.stat().st_size == len(dados):
            return "ja_igual", alvo
        alvo.write_bytes(dados)
        return "conflito_preservado", alvo

    alvo.write_bytes(dados)
    return "copiado", alvo


def post_json(payload, timeout=300):
    req = urllib.request.Request(
        f"{SOURCE_URL}/functions/v1/dre-export",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {SOURCE_ANON}", **_export_secret_header()},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    print(f"Espelho tecnico : {DEST}")
    print(f"Pasta de trabalho: {DEST_TRABALHO}")
    DEST.mkdir(parents=True, exist_ok=True)
    DEST_TRABALHO.mkdir(parents=True, exist_ok=True)

    print("[1/2] Buscando lista de documentos...")
    docs = post_json({"action": "list"}).get("docs") or []
    print(f"      {len(docs)} documentos.\n")

    baixados = pulados = 0
    falhas = []
    trab = {"copiado": 0, "ja_igual": 0, "conflito_preservado": 0, "erro": 0}
    conflitos = []
    escritos = []
    for i, d in enumerate(docs, 1):
        # storage_path = "AAAA-MM/arquivo" -> mantem a mesma estrutura de pastas
        rel = Path(d["storage_path"])
        destino = DEST / rel
        tamanho_esperado = d.get("size_bytes") or 0

        if destino.exists() and destino.stat().st_size == tamanho_esperado:
            pulados += 1
            # ja esta no espelho, mas pode faltar na pasta de trabalho dela
            try:
                r, alvo = copiar_para_pasta_trabalho(destino, d)
                trab[r] += 1
                if r in ("copiado", "conflito_preservado"):
                    escritos.append(alvo)
                if r == "conflito_preservado":
                    conflitos.append(nome_limpo(d["storage_path"]))
            except Exception as e:
                trab["erro"] += 1
                print(f"       aviso: falha ao copiar p/ pasta de trabalho: {str(e)[:100]}")
            print(f"  [{i:2d}/{len(docs)}] ja existe  {rel}")
            continue

        try:
            resp = post_json({"storage_path": d["storage_path"]})
            if "base64" not in resp:
                raise RuntimeError(resp.get("error", "sem base64"))
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(base64.b64decode(resp["base64"]))
            baixados += 1
            try:
                r, alvo = copiar_para_pasta_trabalho(destino, d)
                trab[r] += 1
                if r in ("copiado", "conflito_preservado"):
                    escritos.append(alvo)
                if r == "conflito_preservado":
                    conflitos.append(nome_limpo(d["storage_path"]))
            except Exception as e:
                trab["erro"] += 1
                print(f"       aviso: falha ao copiar p/ pasta de trabalho: {str(e)[:100]}")
            print(f"  [{i:2d}/{len(docs)}] OK         {rel}  ({destino.stat().st_size // 1024} kB)")
        except Exception as e:
            falhas.append((str(rel), str(e)[:120]))
            print(f"  [{i:2d}/{len(docs)}] ERRO       {rel}: {str(e)[:120]}")
        time.sleep(0.15)

    print(f"\n[2/2] Concluido: {baixados} baixados, {pulados} ja existiam, {len(falhas)} falhas.")
    print(f"      Pasta de trabalho: {trab['copiado']} copiados, "
          f"{trab['ja_igual']} ja iguais, {trab['conflito_preservado']} com nome repetido "
          f"(a versao dela foi PRESERVADA), {trab['erro']} erros.")
    if conflitos:
        print("      Nome ja existia com conteudo diferente — gravei a do e-mail com sufixo")
        print("      e mantive a sua intacta:")
        for c in sorted(set(conflitos)):
            print(f"        - {c}")
    if falhas:
        print("Falhas (rode de novo para tentar so estas):")
        for p, e in falhas:
            print(f"  - {p}: {e}")
    else:
        total_mb = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file()) / (1024 * 1024)
        print(f"Total na pasta: {total_mb:.1f} MB")
        print(f"Abrir: {DEST}")

    publicar_no_git(escritos)


if __name__ == "__main__":
    main()
