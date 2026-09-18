"""Os 15 fixtures da especificação do Case Router, ponta a ponta no Router determinístico."""

import pytest

from tests.fixtures.decision_router_loader import build_router, load_cases

CASES = load_cases()
ROUTED_CASES = [case_id for case_id, case in CASES.items() if "replay_of" not in case]
NOT_RESOLVED = {"pass", "skipped"}


def _normalize(result: str) -> str:
    return "not_resolved" if result in NOT_RESOLVED else result


def _assert_trace_subsequence(actual, expected) -> None:
    remaining = iter([(entry.gate, _normalize(entry.result)) for entry in actual])
    for item in expected:
        wanted = (item["gate"], _normalize(item["result"]))
        assert any(pair == wanted for pair in remaining), (
            f"trace não contém {wanted} na ordem esperada; trace real: "
            f"{[(entry.gate, entry.result) for entry in actual]}"
        )


def _assert_expected(route, expected: dict) -> None:
    if "route" in expected:
        assert route.route == expected["route"]
    if "status" in expected:
        assert route.status == expected["status"]
    if "gate_trace" in expected:
        _assert_trace_subsequence(route.gate_trace, expected["gate_trace"])
    if "trace_exact_gates" in expected:
        assert [entry.gate for entry in route.gate_trace] == expected["trace_exact_gates"]
    if "quality_passed" in expected:
        assert route.quality.passed is expected["quality_passed"]
    if "deterministic_resolution" in expected:
        resolution = route.deterministic_resolution
        assert resolution is not None
        for key, value in expected["deterministic_resolution"].items():
            assert getattr(resolution, key) == value
    if "selected_agents" in expected:
        assert [agent.agent_name for agent in route.selected_agents] == expected["selected_agents"]
    if "selected_agents_must_include" in expected:
        names = {agent.agent_name for agent in route.selected_agents}
        assert set(expected["selected_agents_must_include"]) <= names
    for key in ("reused_decision_id", "reused_learning_id", "estimated_ai_calls", "requires_human_approval"):
        if key in expected:
            assert getattr(route, key) == expected[key], key
    if "similarity_reference" in expected:
        sim = route.similarity_reference
        assert sim is not None
        spec = expected["similarity_reference"]
        if "match_level" in spec:
            assert sim.match_level == spec["match_level"]
        assert sim.material_change is spec["material_change"]
        if "material_change_reason" in spec:
            assert spec["material_change_reason"] in sim.material_change_reasons
    if "next_step" in expected:
        for key, value in expected["next_step"].items():
            actual = getattr(route.next_step, key)
            assert (list(actual) if isinstance(actual, tuple) else actual) == value, key
    if "cost" in expected:
        assert route.estimated_ai_cost_avoided_usd == expected["cost"]["usd"]
        assert route.cost_basis == expected["cost"]["basis"]
    if "priority" in expected:
        assert route.priority.human_approval_required is expected["priority"]["human_approval_required"]
        assert list(route.priority.triggered_gates) == expected["priority"]["triggered_gates"]
    if "playbook_id" in expected:
        actual_id = route.playbook.playbook_id if route.playbook else None
        assert actual_id == expected["playbook_id"]
    if "loop_guard" in expected:
        for key, value in expected["loop_guard"].items():
            assert getattr(route.loop_guard, key) == value


@pytest.mark.parametrize("case_id", ROUTED_CASES)
def test_fixture(case_id):
    case = CASES[case_id]
    router, envelope = build_router(case)
    route = router.route(envelope)
    _assert_expected(route, case["expected"])
    assert router.ai_calls_made == 0


def test_f14_idempotency_returns_existing_route_without_new_evaluation():
    case = CASES["F14"]
    original_case = CASES[case["replay_of"]]
    router, envelope = build_router(original_case)
    first = router.route(envelope)
    second = router.route(envelope.model_copy())
    expected = case["expected"]
    assert second is first
    assert second.route == expected["route"]
    assert router.evaluations == expected["evaluations"]
    assert router.replays == expected["replays"]
    assert router.ai_calls_made == 0


def test_all_fixtures_make_zero_ai_calls():
    total = 0
    for case_id in ROUTED_CASES:
        router, envelope = build_router(CASES[case_id])
        router.route(envelope)
        total += router.ai_calls_made
    assert total == 0
