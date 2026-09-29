r"""Roda o ciclo de desvios macro do DRE: motor -> analista-desvios -> decisor.

Uso, no Windows PowerShell (`&&` nao existe no PowerShell 5.1; use `;`), com o
Python do venv do proprio backend -- o Python global nao tem as dependencias:

    cd "C:\Users\tatiana.silva\AGENTE-I.A\sal-intelligence-os\backend"
    .\.venv\Scripts\python.exe -m scripts.run_desvios_macro
    .\.venv\Scripts\python.exe -m scripts.run_desvios_macro --ate 2026-08 --base ORCADO
    .\.venv\Scripts\python.exe -m scripts.run_desvios_macro --json   # so o pacote

O motor (`app/services/desvios_periodo.py`) le os payloads publicados do DRE e
entrega o mesmo numero que qualquer pessoa reproduz. Sem ANTHROPIC_API_KEY o
script para depois do motor e mostra o pacote -- que ja e a parte auditavel.

Onde estao os payloads: `--payloads`, ou a variavel de ambiente `DRE_PAYLOADS`,
ou o caminho padrao do clone local do DRE. O motor nao escreve nada: e leitura.
"""

import argparse
import json
import os
from pathlib import Path

from app.core.config import get_settings
from app.services import desvios_periodo as dp
from app.services.agent_loader import load_agent

PAYLOADS_PADRAO = Path(r"C:\DRE - Demonstrativo de Resultado\app\web\public\payloads")


def pasta_dos_payloads(informada: str | None) -> Path:
    return Path(informada or os.environ.get("DRE_PAYLOADS") or PAYLOADS_PADRAO)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Desvios macro do DRE em quatro janelas.")
    p.add_argument("--payloads", help="pasta dos payloads publicados do DRE")
    p.add_argument("--ate", help="competencia final (padrao: a mais recente publicada)")
    p.add_argument("--base", default="FLEXIBILIZADO", choices=dp.BASES)
    p.add_argument("--materialidade", type=str, default=str(dp.MATERIALIDADE_PADRAO),
                   help="piso por mes da janela, em reais")
    p.add_argument("--grupo", action="store_true",
                   help="agrega por grupo do DRE (custos variaveis, MDO, estrutural, logisticos)")
    p.add_argument("--json", action="store_true", help="imprime o pacote do motor e sai")
    args = p.parse_args(argv)

    pasta = pasta_dos_payloads(args.payloads)
    if not pasta.exists():
        print(f"pasta de payloads nao encontrada: {pasta}")
        print("passe --payloads ou defina DRE_PAYLOADS")
        return 1

    serie = dp.carregar_serie(pasta)
    if not serie:
        print(f"nenhum payload em {pasta}")
        return 1

    from decimal import Decimal
    competencia = args.ate or max(serie)
    pacote = dp.resumo(serie, competencia, args.base, Decimal(args.materialidade), args.grupo)

    if args.json:
        print(json.dumps(pacote, ensure_ascii=False, indent=1))
        return 0

    print(f"payloads: {len(serie)} ({min(serie)} a {max(serie)})")
    print("janela final: {} | base: {} | piso por mes: R$ {}\n".format(competencia, args.base,
                                                                   pacote["materialidade"]))
    for janela in pacote["janelas"]:
        marca = "" if janela["completa"] else "  << incompleta"
        print(f'  {janela["tipo"]:<10} {len(janela["competencias"]):2d} meses{marca}')

    print()
    print(f'desvios macro por {pacote["nivel"]}: {len(pacote["macro"])}')
    for item in pacote["macro"]:
        print(f'  {item["rotulo"][:36]:<36} {item["veredito"]:<12} '
              f'{item["persistencia"]}/{item["janelas_avaliadas"]} janelas  '
              f'{item["impacto_maior_janela"]:>14}')

    if not get_settings().anthropic_api_key:
        print("\nSem ANTHROPIC_API_KEY: o pacote acima e a parte deterministica.")
        print("Com a chave, ele vai para `analista-desvios` e depois para `decisor`.")
        return 0

    analista, decisor = load_agent("analista-desvios"), load_agent("decisor")
    print(f"\nagentes prontos: {analista.name} -> {decisor.name}")
    print("A chamada aos agentes usa o mesmo caminho do Orchestrator; o pacote acima e a evidencia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
