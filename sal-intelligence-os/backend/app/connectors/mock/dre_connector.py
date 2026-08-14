"""Conector mock de DRE/orçamento — dados fictícios de examples/dre_margin_case.md.

Decisão registrada na apresentação da Fase 0: nenhuma das 3 bases Supabase reais da SAL
(relatorios-raw, Gente & Gestao, pendency-tracker) tem DRE/orçamento/faturamento consolidado
hoje. Este conector fica mock até uma fonte real ser localizada e mapeada — ver
docs/IMPLEMENTATION_BACKLOG.md Fase 1 e o risco registrado no README da Fase 0.
"""

from app.connectors.base import DreConnector


class MockDreConnector(DreConnector):
    def get_dre(self, period: str) -> dict:
        return {
            "period": period,
            "receita_bruta": {"orcado": 10_500_000, "realizado": 11_400_000},
            "deducoes": {"orcado": 500_000, "realizado": 600_000},
            "receita_liquida": {"orcado": 10_000_000, "realizado": 10_800_000},
            "custos": {"orcado": 6_400_000, "realizado": 7_560_000},
            "lucro_bruto": {"orcado": 3_600_000, "realizado": 3_240_000},
            "margem_bruta_pct": {"orcado": 36.0, "realizado": 30.0},
            "despesas_operacionais": {"orcado": 2_100_000, "realizado": 2_180_000},
            "ebitda": {"orcado": 1_500_000, "realizado": 1_060_000},
        }

    def get_concentration(self, period: str) -> dict:
        return {
            "period": period,
            "fatores_impacto": [
                {"fator": "volume_receita", "impacto": 288_000},
                {"fator": "descontos_adicionais", "impacto": -180_000},
                {"fator": "mix", "impacto": -120_000},
                {"fator": "custo_aquisicao", "impacto": -210_000},
                {"fator": "frete_logistica", "impacto": -78_000},
                {"fator": "devolucoes_avarias", "impacto": -60_000},
            ],
            "concentracao": {
                "linha_premium_pct": 62,
                "top_15_clientes_pct": 68,
                "regiao_sul_pct": 54,
                "top_4_vendedores_descontos_pct": 57,
                "top_2_fornecedores_aquisicao_pct": 71,
                "top_3_rotas_frete_pct": 64,
            },
        }
