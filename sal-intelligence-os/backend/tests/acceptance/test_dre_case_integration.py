"""Teste 6 de docs/ACCEPTANCE_TESTS.md (examples/dre_margin_case.md), ponta a ponta com os agentes
reais via Claude API. Requer ANTHROPIC_API_KEY configurada — sem ela, pulado (não é um teste que
roda em qualquer máquina sem custo/rede, então não entra no CI padrão por enquanto).
"""

import pytest

from app.core.config import get_settings
from app.services.orchestrator import Orchestrator

pytestmark = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="requer ANTHROPIC_API_KEY real; roda sob demanda, não no CI padrão",
)

CASE_DESCRIPTION = """
DRE do período: receita bruta orçada R$ 10.500.000 / realizada R$ 11.400.000.
Margem bruta orçada 36,0% / realizada 30,0% (queda de 6,0 p.p.).
EBITDA orçado R$ 1.500.000 / realizado R$ 1.060.000.
Concentração: Linha Premium 62% da perda; 15 clientes 68%; Região Sul 54%;
4 vendedores 57% dos descontos adicionais; 2 fornecedores 71% do aumento de aquisição;
3 rotas 64% do aumento de frete.
Pergunta: quais fatores explicam a perda de margem e qual intervenção recupera resultado
sem comprometer clientes estratégicos e volume?
"""


def test_dre_case_does_not_conclude_single_cause():
    orchestrator = Orchestrator()
    result = orchestrator.orchestrate("dre_margin_cash", CASE_DESCRIPTION)

    assert result.diagnosis_error is None, result.diagnosis_error
    diagnosis = result.diagnosis
    assert diagnosis is not None

    # não pode reconhecer só "desconto" ou só "Linha Premium" como causa única
    assert len(diagnosis.hypotheses) >= 2, "precisa testar mais de uma hipótese, não fechar em causa única"

    # as 3 recomendações têm que cobrir os 3 horizontes (validado também pelo schema)
    assert {r.type for r in diagnosis.recommendations} == {"containment", "structural", "optimization"}

    # não pode encerrar em "continuar analisando" sem próximo passo
    assert diagnosis.decision_status != "NEEDS_INVESTIGATION" or diagnosis.missing_data
