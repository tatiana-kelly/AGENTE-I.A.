"""Contrato sal.decision-route/1.0: objeto fechado e invariantes das cinco rotas."""

import pytest
from pydantic import ValidationError

from app.decision_router import decision_route_json_schema
from app.decision_router.contract import DecisionRoute
from tests.fixtures.decision_router_loader import build_router, load_cases

CASES = load_cases()


def _route(case_id: str) -> DecisionRoute:
    router, envelope = build_router(CASES[case_id])
    return router.route(envelope)


def _mutate(route: DecisionRoute, **changes) -> dict:
    data = route.model_dump(mode="json")
    data.update(changes)
    return data


def test_schema_is_closed():
    schema = decision_route_json_schema()
    assert schema["additionalProperties"] is False
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False


def test_unknown_property_rejected():
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(_route("F05"), model="claude-sonnet-5"))


def test_every_fixture_route_round_trips():
    for case_id, case in CASES.items():
        if "replay_of" in case:
            continue
        route = _route(case_id)
        assert DecisionRoute.model_validate(route.model_dump(mode="json")) == route


def test_no_agent_rejects_agents_and_calls():
    route = _route("F01")
    agent = {"agent_name": "investigador", "role": "investigate", "why": "x"}
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(route, selected_agents=[agent]))
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(route, estimated_ai_calls=1))


def test_reuse_requires_decision_id_and_human_approval():
    route = _route("F06")
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(route, reused_decision_id=None))
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(route, requires_human_approval=False))


def test_one_agent_requires_exactly_one():
    route = _route("F10")
    extra = {"agent_name": "provocador", "role": "challenge", "why": "x"}
    data = route.model_dump(mode="json")
    data["selected_agents"].append(extra)
    data["estimated_ai_calls"] = 3
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(data)


def test_multi_agent_limits_specialists():
    data = _route("F05").model_dump(mode="json")
    data["selected_agents"].append({"agent_name": "entrega", "role": "specialist", "why": "x"})
    data["estimated_ai_calls"] = len(data["selected_agents"]) + 1
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(data)


def test_unknown_case_type_cannot_select_agents():
    data = _route("F12").model_dump(mode="json")
    data["route"] = "MULTI_AGENT"
    data["selected_agents"] = [
        {"agent_name": "investigador", "role": "investigate", "why": "x"},
        {"agent_name": "financeiro-dre", "role": "specialist", "why": "x"},
    ]
    data["estimated_ai_calls"] = 3
    data["next_step"] = {"action": "run_agents", "owner_system": "ai-orchestrator"}
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(data)


def test_failed_quality_cannot_select_agents():
    data = _route("F04").model_dump(mode="json")
    data["route"] = "ONE_AGENT"
    data["deterministic_resolution"] = None
    data["selected_agents"] = [{"agent_name": "financeiro-dre", "role": "specialist", "why": "x"}]
    data["estimated_ai_calls"] = 2
    data["next_step"] = {"action": "run_agents", "owner_system": "ai-orchestrator"}
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(data)


def test_escalated_requires_await_human():
    data = _route("F15").model_dump(mode="json")
    data["next_step"] = {"action": "collect_evidence", "owner_system": "human", "missing_evidence": ["x"]}
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(data)


def test_cost_basis_unknown_cannot_carry_value():
    with pytest.raises(ValidationError):
        DecisionRoute.model_validate(_mutate(_route("F01"), estimated_ai_cost_avoided_usd=1.5))
