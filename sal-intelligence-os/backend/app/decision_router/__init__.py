"""Decision Router (Case Router / Knowledge Gate) — camada nova, determinística e isolada.

Recebe um AlertBase envolvido em AlertEnvelope e devolve um DecisionRoute (sal.decision-route/1.0).
Não chama IA, não grava Decision, não cria ação e não altera nenhum ativo existente.
"""

from app.decision_router.contract import CONTRACT_VERSION, DecisionRoute, decision_route_json_schema
from app.decision_router.inputs import AlertEnvelope
from app.decision_router.policy import RouterPolicy, b7_recommended_reuse, build_default_policy
from app.decision_router.router import DecisionRouter

__all__ = [
    "CONTRACT_VERSION",
    "AlertEnvelope",
    "DecisionRoute",
    "DecisionRouter",
    "RouterPolicy",
    "b7_recommended_reuse",
    "build_default_policy",
    "decision_route_json_schema",
]
