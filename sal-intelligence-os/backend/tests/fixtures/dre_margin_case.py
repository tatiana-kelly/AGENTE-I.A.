"""Estrutura o caso de examples/dre_margin_case.md para uso em testes/scripts (não duplica o texto —
os números vêm de lá, e o mock connector também os usa)."""

from app.connectors.mock.dre_connector import MockDreConnector

PERIOD = "2026-07"


def build_alert_payload() -> dict:
    connector = MockDreConnector()
    dre = connector.get_dre(PERIOD)
    margem = dre["margem_bruta_pct"]
    return {
        "metric_id": "margem-bruta",
        "title": "Queda de margem bruta na DRE",
        "period": PERIOD,
        "current_value": margem["realizado"],
        "reference_value": margem["orcado"],
        "materiality": abs(dre["ebitda"]["realizado"] - dre["ebitda"]["orcado"]),
        "severity": "high",
        "source_quality": "validated",
        "concentration": [
            {"dimensao": "linha_produto", "chave": "Linha Premium", "participacao_pct": 62},
            {"dimensao": "cliente", "chave": "top_15", "participacao_pct": 68},
            {"dimensao": "regiao", "chave": "Sul", "participacao_pct": 54},
        ],
    }
