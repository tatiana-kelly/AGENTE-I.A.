"""Motor de desvios por janela: mes, trimestre, semestre e ano, contra tres bases.

Pedido da Tatiana em 28/09/2026: *"identificara os desvios mensais, trimestrais,
semestrais, anuais, que fara comparativo, vai identificar ... a ideia e identificar
os desvios macros"*.

Por que existe, se ja ha o `DrePayloadAdapter`
----------------------------------------------
O adaptador le **um** payload -- a competencia corrente -- e compara realizado x
orcado no mes. E o suficiente para abrir alerta do mes, e nada alem disso. Um
desvio de um mes nao distingue **evento** de **tendencia**: a conta que estourou
em agosto pode ter voltado ao normal, e a conta que desviou pouco em cada mes
pode estar levando o semestre inteiro.

Este motor le a serie publicada (33 payloads, 2023-12 a 2026-08), soma por janela
e compara a mesma conta em quatro janelas. O produto e o **desvio macro**: conta
material e desfavoravel em varias janelas seguidas, na mesma direcao.

O que ele nao faz
-----------------
Nao conclui, nao explica causa e nao recomenda. Entrega numero reproduzivel --
qualquer pessoa refaz a conta a partir dos mesmos payloads. A leitura e do agente
`analista-desvios`; a decisao, do `decisor`. Motor que opina vira opiniao sem
auditoria, e o DRE tem a regra de que todo numero precisa poder ser reproduzido
por quem duvidar dele.

Dinheiro em `Decimal`, nunca float -- regra do projeto do DRE, de onde vem o dado.

Escopo herdado, de proposito
----------------------------
As exclusoes sao as mesmas do `DrePayloadAdapter` (decisao da Tatiana em
19/09/2026): linhas restritas e folha/pro-labore/lucros ficam de fora, e a regra
mora num lugar so -- aqui ela e importada, nao reescrita.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.decision_router.adapters.dre_payload import RESTRICTED_FROM_ID, SENSITIVE

ZERO = Decimal(0)
CENTAVO = Decimal("0.01")


def _cent(valor: Decimal) -> Decimal:
    """Ao centavo, ROUND_HALF_UP -- o arredondamento da Auditoria, como no DRE.

    O FLEXIBILIZADO vem do payload com muitas casas (e coeficiente aplicado sobre
    o orcado), e sem isto o impacto sai com vinte e uma casas decimais.
    """
    return Decimal(valor).quantize(CENTAVO, ROUND_HALF_UP)

#: Bases de comparacao. FLEXIBILIZADO e ORCADO vem do proprio payload; ANO_ANTERIOR
#: e a mesma janela deslocada doze meses.
BASES = ("FLEXIBILIZADO", "ORCADO", "ANO_ANTERIOR")

#: Meses por janela. `mes` existe para que a serie curta tambem seja comparavel.
TAMANHO = {"mes": 1, "trimestre": 3, "semestre": 6, "ano": 12}

#: Materialidade **por mes** da janela. Sem um piso, a lista enche de conta pequena
#: com percentual grande -- foi o que aconteceu com PIS a +1.055% na sazonalidade
#: do planejamento.
#:
#: E por mes, e nao por janela, por um motivo que decide o resultado: a soma de uma
#: janela longa carrega o mesmo desvio de um mes so. Um evento de R$ 60 mil em
#: agosto continua valendo R$ 60 mil no trimestre, no semestre e no ano -- com piso
#: fixo ele apareceria nas quatro janelas e seria lido como tendencia. Com o piso
#: proporcional, o evento cabe no mes e some nas janelas longas, que e o que separa
#: "estourou uma vez" de "estoura todo mes".
MATERIALIDADE_PADRAO = Decimal(20000)


def materialidade_da_janela(janela: Janela, por_mes: Decimal = MATERIALIDADE_PADRAO) -> Decimal:
    """O piso cresce com o numero de meses **presentes**, nao com o nominal: uma
    janela anual com oito meses publicados nao pode exigir piso de doze."""
    return por_mes * max(1, len(janela.competencias))


@dataclass(frozen=True)
class Janela:
    tipo: str
    rotulo: str
    competencias: tuple[str, ...]

    @property
    def completa(self) -> bool:
        return len(self.competencias) == TAMANHO[self.tipo]


@dataclass(frozen=True)
class Desvio:
    """Uma conta -- ou um grupo -- numa janela, contra uma base."""

    #: int para conta analitica; str para grupo (id do grupo, ou o nome do derivado).
    linha_id: int | str
    rotulo: str
    classe: str
    janela: str
    base: str
    realizado: Decimal
    referencia: Decimal
    #: Positivo = pos no EBITDA; negativo = tirou. Usa `sinal_ebitda` do cadastro.
    impacto: Decimal
    #: Participacao no desvio desfavoravel total da janela, em %.
    participacao: Decimal


@dataclass(frozen=True)
class DesvioMacro:
    """A mesma conta -- ou grupo -- nas quatro janelas: separa evento de tendencia."""

    linha_id: int | str
    rotulo: str
    base: str
    por_janela: dict[str, Decimal]
    #: Em quantas janelas a conta e material e desfavoravel.
    persistencia: int
    janelas_avaliadas: int
    veredito: str
    impacto_maior_janela: Decimal
    observacao: str = ""
    evidencia: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def carregar_serie(pasta: Path) -> dict[str, dict]:
    """{competencia: payload} de todos os payloads publicados da pasta."""
    serie = {}
    for caminho in sorted(Path(pasta).glob("*.json")):
        documento = json.loads(caminho.read_text(encoding="utf-8"))
        competencia = str(documento.get("competencia") or caminho.stem)
        serie[competencia] = documento
    return serie


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (TypeError, ValueError, ArithmeticError):
        return None


def _no_escopo(linha: dict, incluir_folha: bool = False) -> bool:
    """`incluir_folha` so e ligado na visao por grupo.

    A exclusao de folha, pro-labore e lucros (decisao de 19/09/2026) existe para
    que salario de pessoa nomeada nao chegue ao agente. Num agregado de grupo --
    `CUSTO COM MDO` inteiro, num trimestre -- nao ha pessoa a expor, e sem ele o
    grupo que a Tatiana pediu nominalmente em 29/09/2026 sairia vazio e com
    numero errado. Conta a conta o filtro continua ligado.
    """
    if linha.get("nivel") != "ANALITICA":
        return False
    if int(linha.get("linha_id") or 0) >= RESTRICTED_FROM_ID:
        return False
    if not incluir_folha and SENSITIVE.search(str(linha.get("rotulo") or "")):
        return False
    return linha.get("sinal_ebitda") in (1, -1)


# ---------------------------------------------------------------------------
# Janelas
# ---------------------------------------------------------------------------

def janelas_de(competencia_final: str, disponiveis: list[str]) -> list[Janela]:
    """As quatro janelas que terminam em `competencia_final`, com o que existe.

    Uma janela incompleta nao e descartada: ela e marcada, e o agente recebe a
    marca. Esconder janela incompleta seria esconder que o ano corrente tem oito
    meses e nao doze.
    """
    ano, mes = (int(p) for p in competencia_final.split("-"))
    existentes = set(disponiveis)
    saida = []
    for tipo, tamanho in TAMANHO.items():
        meses = []
        a, m = ano, mes
        for _ in range(tamanho):
            competencia = f"{a:04d}-{m:02d}"
            if competencia in existentes:
                meses.append(competencia)
            m -= 1
            if m == 0:
                a, m = a - 1, 12
        saida.append(Janela(tipo, _rotulo(tipo, competencia_final, tamanho), tuple(sorted(meses))))
    return saida


def _rotulo(tipo: str, competencia_final: str, tamanho: int) -> str:
    if tipo == "mes":
        return competencia_final
    return f"{tamanho} meses ate {competencia_final}"


def deslocar_um_ano(janela: Janela, disponiveis: list[str]) -> Janela:
    """A mesma janela doze meses antes -- a base ANO_ANTERIOR."""
    existentes = set(disponiveis)
    meses = []
    for competencia in janela.competencias:
        ano, mes = (int(p) for p in competencia.split("-"))
        anterior = f"{ano - 1:04d}-{mes:02d}"
        if anterior in existentes:
            meses.append(anterior)
    return Janela(janela.tipo, janela.rotulo + " (ano anterior)", tuple(sorted(meses)))


# ---------------------------------------------------------------------------
# Desvios
# ---------------------------------------------------------------------------

def _somar(serie: dict[str, dict], competencias, campo: str,
           incluir_folha: bool = False) -> dict[int, Decimal]:
    total: dict[int, Decimal] = {}
    for competencia in competencias:
        documento = serie.get(competencia)
        if not documento:
            continue
        for linha in documento.get("matriz") or []:
            if not _no_escopo(linha, incluir_folha):
                continue
            valor = _decimal(linha.get(campo))
            if valor is None:
                continue
            linha_id = int(linha["linha_id"])
            total[linha_id] = total.get(linha_id, ZERO) + valor
    return total


def _cadastro(serie: dict[str, dict], incluir_folha: bool = False) -> dict[int, dict]:
    """Rotulo, classe e sinal de cada linha, do payload mais recente que a traz."""
    saida: dict[int, dict] = {}
    for competencia in sorted(serie):
        for linha in serie[competencia].get("matriz") or []:
            if _no_escopo(linha, incluir_folha):
                saida[int(linha["linha_id"])] = {
                    "rotulo": str(linha.get("rotulo") or ""),
                    "classe": str(linha.get("classe") or ""),
                    "sinal": int(linha["sinal_ebitda"]),
                }
    return saida


def desvios_da_janela(serie, janela: Janela, base: str, materialidade=MATERIALIDADE_PADRAO) -> list[Desvio]:
    """Desvios materiais da janela contra a base, do mais desfavoravel ao mais favoravel.

    `materialidade` e o piso **por mes**; o piso da janela sai de
    `materialidade_da_janela`.
    """
    piso = materialidade_da_janela(janela, materialidade)
    cadastro = _cadastro(serie)
    realizado = _somar(serie, janela.competencias, "REALIZADO")
    if base == "ANO_ANTERIOR":
        anterior = deslocar_um_ano(janela, list(serie))
        if not anterior.competencias:
            return []
        referencia = _somar(serie, anterior.competencias, "REALIZADO")
    else:
        referencia = _somar(serie, janela.competencias, base)

    brutos = []
    for linha_id, valor in realizado.items():
        if linha_id not in referencia or linha_id not in cadastro:
            continue
        ref = referencia[linha_id]
        impacto = _cent(Decimal(cadastro[linha_id]["sinal"]) * (valor - ref))
        if abs(impacto) < piso:
            continue
        brutos.append((linha_id, valor, ref, impacto))

    desfavoravel_total = sum((-i for _, _, _, i in brutos if i < ZERO), ZERO)
    saida = []
    for linha_id, valor, ref, impacto in sorted(brutos, key=lambda item: item[3]):
        participacao = ZERO
        if impacto < ZERO and desfavoravel_total > ZERO:
            participacao = (-impacto / desfavoravel_total * 100).quantize(Decimal("0.01"))
        saida.append(Desvio(
            linha_id=linha_id,
            rotulo=cadastro[linha_id]["rotulo"],
            classe=cadastro[linha_id]["classe"],
            janela=janela.tipo,
            base=base,
            realizado=_cent(valor),
            referencia=_cent(ref),
            impacto=impacto,
            participacao=participacao,
        ))
    return saida


# ---------------------------------------------------------------------------
# Grupos: a mesma leitura um nivel acima
# ---------------------------------------------------------------------------

#: Grupos que nao existem na hierarquia do DRE e que a Tatiana definiu em
#: 29/09/2026: *"custos logisticos = transferencias, coletas, entrega
#: filial/agregado + entregas parceiros"*. Nao e o mesmo que FRETE TERCEIRIZADO,
#: que traz tambem Ajudantes PJ e Descargas -- e Descargas e hoje a maior
#: tendencia da serie, entao junta-la mudaria a leitura do grupo.
GRUPOS_DERIVADOS = {
    "CUSTOS LOGISTICOS": (
        "Transferência Agregado", "Transferência Parceiro",
        "Coleta Agregado", "Coleta Parceiro",
        "Entrega Agregado", "Entrega Parceiro",
    ),
}


def grupos_do_cadastro(serie: dict[str, dict]) -> dict[str, tuple[str, tuple[int, ...]]]:
    """{chave: (rotulo, linhas analiticas)} a partir da hierarquia do proprio DRE.

    Cada GRUPO e TOTALIZADOR recebe as analiticas que descendem dele, em qualquer
    profundidade. Nao ha uma segunda arvore aqui: a que vale e a do cadastro, a
    mesma que a tela do DRE desenha.
    """
    documento = serie[max(serie)]
    matriz = documento.get("matriz") or []
    pai = {int(l["linha_id"]): l.get("pai") for l in matriz}
    rotulo = {int(l["linha_id"]): str(l.get("rotulo") or "") for l in matriz}
    nivel = {int(l["linha_id"]): l.get("nivel") for l in matriz}

    def ancestrais(linha_id):
        atual, vistos = pai.get(linha_id), []
        while atual is not None and atual not in vistos:
            vistos.append(atual)
            atual = pai.get(int(atual))
        return vistos

    grupos: dict[str, list[int]] = {}
    for linha in matriz:
        if not _no_escopo(linha, incluir_folha=True):
            continue
        linha_id = int(linha["linha_id"])
        for ancestral in ancestrais(linha_id):
            if nivel.get(int(ancestral)) in ("GRUPO", "TOTALIZADOR"):
                grupos.setdefault(str(int(ancestral)), []).append(linha_id)

    saida = {chave: (rotulo.get(int(chave), chave), tuple(sorted(set(ids))))
             for chave, ids in grupos.items()}

    por_rotulo = {r: i for i, r in rotulo.items()}
    for nome, contas in GRUPOS_DERIVADOS.items():
        ids = tuple(sorted(por_rotulo[c] for c in contas if c in por_rotulo))
        if ids:
            saida[nome] = (nome.title(), ids)
    return saida


def desvios_por_grupo(serie, janela: Janela, base: str,
                      materialidade=MATERIALIDADE_PADRAO) -> list[Desvio]:
    """O mesmo desvio da janela, somado por grupo em vez de conta a conta.

    O impacto do grupo e a soma dos impactos das analiticas -- `sinal x (real -
    ref)` de cada uma --, e nao a diferenca de dois totais. Dentro de um grupo
    convivem contas de sinais opostos (indenizacao e recuperacao de indenizacao):
    somar os totais antes do sinal apagaria uma contra a outra.
    """
    piso = materialidade_da_janela(janela, materialidade)
    cadastro = _cadastro(serie, incluir_folha=True)
    grupos = grupos_do_cadastro(serie)
    realizado = _somar(serie, janela.competencias, "REALIZADO", incluir_folha=True)
    if base == "ANO_ANTERIOR":
        anterior = deslocar_um_ano(janela, list(serie))
        if not anterior.competencias:
            return []
        referencia = _somar(serie, anterior.competencias, "REALIZADO", incluir_folha=True)
    else:
        referencia = _somar(serie, janela.competencias, base, incluir_folha=True)

    brutos = []
    for chave, (rotulo, linhas) in grupos.items():
        real = ref = impacto = ZERO
        tem = False
        for linha_id in linhas:
            if linha_id not in realizado or linha_id not in referencia:
                continue
            tem = True
            real += realizado[linha_id]
            ref += referencia[linha_id]
            impacto += Decimal(cadastro[linha_id]["sinal"]) * (realizado[linha_id] - referencia[linha_id])
        impacto = _cent(impacto)
        if not tem or abs(impacto) < piso:
            continue
        brutos.append((chave, rotulo, real, ref, impacto))

    desfavoravel_total = sum((-i for *_, i in brutos if i < ZERO), ZERO)
    saida = []
    for chave, rotulo, real, ref, impacto in sorted(brutos, key=lambda item: item[4]):
        participacao = ZERO
        if impacto < ZERO and desfavoravel_total > ZERO:
            participacao = (-impacto / desfavoravel_total * 100).quantize(Decimal("0.01"))
        saida.append(Desvio(
            linha_id=chave, rotulo=rotulo, classe="GRUPO", janela=janela.tipo, base=base,
            realizado=_cent(real), referencia=_cent(ref), impacto=impacto,
            participacao=participacao,
        ))
    return saida


# ---------------------------------------------------------------------------
# O produto: o desvio macro
# ---------------------------------------------------------------------------

#: Vereditos. Sao descricoes do padrao observado, nao julgamento de causa.
TENDENCIA = "tendência"
EVENTO = "evento"
ALTERNANCIA = "alternância"
FAVORAVEL = "favorável"


def desvios_macro(serie, competencia_final: str, base: str = "FLEXIBILIZADO",
                  materialidade=MATERIALIDADE_PADRAO, por_grupo: bool = False) -> list[DesvioMacro]:
    """A mesma conta nas quatro janelas: o que se repete e o que foi de um mes so.

    - **tendência**: desfavoravel e material em todas as janelas completas -- o
      desvio esta na operacao, nao no mes;
    - **evento**: aparece so na janela mais curta -- provavel fato isolado;
    - **alternância**: desfavoravel numas janelas e favoravel noutras -- o numero
      do mes nao sustenta conclusao sozinho.
    """
    disponiveis = list(serie)
    janelas = janelas_de(competencia_final, disponiveis)
    por_linha: dict[int | str, dict[str, Decimal]] = {}
    materiais: dict[int | str, set[str]] = {}
    avaliadas: dict[int | str, int] = {}
    cadastro = _cadastro(serie, incluir_folha=por_grupo)
    rotulos_grupo = {c: r for c, (r, _) in grupos_do_cadastro(serie).items()} if por_grupo else {}
    medir = desvios_por_grupo if por_grupo else desvios_da_janela

    for janela in janelas:
        if not janela.competencias:
            continue
        for desvio in medir(serie, janela, base, materialidade):
            por_linha.setdefault(desvio.linha_id, {})[janela.tipo] = desvio.impacto
            if desvio.impacto < ZERO:
                materiais.setdefault(desvio.linha_id, set()).add(janela.tipo)
        for linha_id in por_linha:
            avaliadas[linha_id] = avaliadas.get(linha_id, 0) + 1

    saida = []
    for linha_id, por_janela in por_linha.items():
        desfavoraveis = materiais.get(linha_id, set())
        favoraveis = {t for t, v in por_janela.items() if v > ZERO}
        total_janelas = len([j for j in janelas if j.competencias])

        if len(desfavoraveis) >= 3 and not favoraveis:
            veredito, observacao = TENDENCIA, (
                f"desfavorável e material em {len(desfavoraveis)} das {total_janelas} "
                f"janelas: o desvio se repete, não é do mês")
        elif desfavoraveis and favoraveis:
            veredito, observacao = ALTERNANCIA, (
                "desfavorável em {} e favorável em {}: o número de uma janela só não "
                "sustenta conclusão".format(", ".join(sorted(desfavoraveis)), ", ".join(sorted(favoraveis))))
        elif desfavoraveis == {"mes"}:
            veredito, observacao = EVENTO, (
                "material apenas no mês: provável fato isolado, confirmar antes de tratar "
                "como recorrente")
        elif desfavoraveis:
            veredito, observacao = EVENTO, (
                "material em {}, e não em todas as janelas".format(", ".join(sorted(desfavoraveis))))
        elif favoraveis:
            # Desvio favoravel tambem e desvio. `CUSTO COM MDO` veio R$ 1,17 milhao
            # abaixo do previsto no ano: pode ser economia real ou previsao errada,
            # e as duas leituras importam. Descartar o lado favoravel deixaria a
            # analise so com o que da ma noticia.
            veredito, observacao = FAVORAVEL, (
                f"favorável e material em {', '.join(sorted(favoraveis))}: confirmar se é "
                f"economia real ou previsão superestimada")
        else:
            continue

        maior = min(por_janela.values()) if desfavoraveis else max(por_janela.values())
        saida.append(DesvioMacro(
            linha_id=linha_id,
            rotulo=rotulos_grupo.get(linha_id) or cadastro.get(linha_id, {}).get("rotulo", str(linha_id)),
            base=base,
            por_janela=dict(por_janela),
            persistencia=len(desfavoraveis),
            janelas_avaliadas=total_janelas,
            veredito=veredito,
            impacto_maior_janela=maior,
            observacao=observacao,
            evidencia=tuple("{}: {}".format(j.tipo, " ".join(j.competencias)) for j in janelas if j.competencias),
        ))
    ordem = {TENDENCIA: 0, ALTERNANCIA: 1, EVENTO: 2, FAVORAVEL: 3}
    return sorted(saida, key=lambda d: (ordem.get(d.veredito, 9), d.impacto_maior_janela))


def resumo(serie, competencia_final: str, base: str = "FLEXIBILIZADO",
           materialidade=MATERIALIDADE_PADRAO, por_grupo: bool = False) -> dict:
    """Pacote pronto para o agente: janelas, desvios de cada uma e a leitura macro.

    Serializavel de proposito -- valores em texto, como o payload do DRE, para que
    o agente receba o mesmo numero que qualquer pessoa reproduz.
    """
    disponiveis = list(serie)
    janelas = janelas_de(competencia_final, disponiveis)
    macro = desvios_macro(serie, competencia_final, base, materialidade, por_grupo)
    medir = desvios_por_grupo if por_grupo else desvios_da_janela
    return {
        "competencia_final": competencia_final,
        "base": base,
        "nivel": "grupo" if por_grupo else "conta",
        "materialidade": str(materialidade),
        "janelas": [
            {"tipo": j.tipo, "rotulo": j.rotulo, "competencias": list(j.competencias),
             "completa": j.completa}
            for j in janelas
        ],
        "por_janela": {
            j.tipo: [
                {"linha_id": d.linha_id, "rotulo": d.rotulo, "classe": d.classe,
                 "realizado": str(d.realizado), "referencia": str(d.referencia),
                 "impacto": str(d.impacto), "participacao": str(d.participacao)}
                for d in medir(serie, j, base, materialidade)
            ]
            for j in janelas if j.competencias
        },
        "macro": [
            {"linha_id": d.linha_id, "rotulo": d.rotulo, "veredito": d.veredito,
             "persistencia": d.persistencia, "janelas_avaliadas": d.janelas_avaliadas,
             "impacto_maior_janela": str(d.impacto_maior_janela),
             "por_janela": {k: str(v) for k, v in d.por_janela.items()},
             "observacao": d.observacao}
            for d in macro
        ],
    }
