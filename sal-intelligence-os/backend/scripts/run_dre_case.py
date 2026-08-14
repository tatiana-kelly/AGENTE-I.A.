"""Roda o caso obrigatório de validação (examples/dre_margin_case.md) ponta a ponta —
requisito explícito do CLAUDE_CODE_HANDOFF.md antes de considerar o MVP concluído.

Uso:
    cd backend && python -m scripts.run_dre_case

Sem ANTHROPIC_API_KEY configurada, mostra só o Alert gerado a partir do conector mock
(a parte determinística) e explica o que falta para rodar a investigação completa.
"""

import json

from app.connectors.mock.dre_connector import MockDreConnector
from app.core.config import get_settings

PERIOD = "2026-07"


def build_case_description() -> tuple[dict, str]:
    connector = MockDreConnector()
    dre = connector.get_dre(PERIOD)
    concentration = connector.get_concentration(PERIOD)

    description = f"""
DRE do período {PERIOD} (dados fictícios de examples/dre_margin_case.md):
Receita bruta: orçado R$ {dre['receita_bruta']['orcado']:,} / realizado R$ {dre['receita_bruta']['realizado']:,}
Margem bruta: orçado {dre['margem_bruta_pct']['orcado']}% / realizado {dre['margem_bruta_pct']['realizado']}%
EBITDA: orçado R$ {dre['ebitda']['orcado']:,} / realizado R$ {dre['ebitda']['realizado']:,}

Fatores de impacto: {json.dumps(concentration['fatores_impacto'], ensure_ascii=False)}
Concentração: {json.dumps(concentration['concentracao'], ensure_ascii=False)}

Pergunta: quais fatores explicam a perda de margem e qual intervenção recupera resultado
sem comprometer clientes estratégicos e volume?
""".strip()
    return dre, description


def main() -> None:
    dre, description = build_case_description()
    print("=== ALERT (determinístico, via MockDreConnector) ===")
    print(json.dumps(dre, indent=2, ensure_ascii=False))
    print()
    print("=== CASO PARA OS AGENTES ===")
    print(description)
    print()

    if not get_settings().anthropic_api_key:
        print(
            "ANTHROPIC_API_KEY não configurada — parando aqui.\n"
            "Configure no backend/.env (copie de .env.example) e rode de novo para ver a "
            "investigação completa (Coordenador -> Investigador -> especialistas -> Provocador -> "
            "Soluções e Ações Práticas -> Diagnosis estruturado)."
        )
        return

    from app.services.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    result = orchestrator.orchestrate("dre_margin_cash", description)

    for step in result.transcript:
        print(f"\n=== {step['agent']} ===")
        print(step["output"])

    print("\n=== DIAGNOSIS ESTRUTURADO ===")
    if result.diagnosis_error:
        print(f"FALHOU a validação do contrato: {result.diagnosis_error}")
    else:
        print(result.diagnosis.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
