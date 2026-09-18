"""Monta Router + provedores em memória a partir de tests/fixtures/decision_router_cases.json."""

import json
from pathlib import Path

from app.decision_router import AlertEnvelope, DecisionRouter, build_default_policy
from app.decision_router.inputs import MemoryEntry, PatternStats, Playbook, ReferenceCase
from app.decision_router.policy import MetricThresholds, RouterPolicy
from app.decision_router.providers import (
    InMemoryMemoryLedgerProvider,
    InMemoryPatternStatsProvider,
    InMemoryPlaybookProvider,
    InMemoryRouteStore,
    InMemorySimilarityCaseProvider,
)

CASES_PATH = Path(__file__).with_name("decision_router_cases.json")


def load_document() -> dict:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def load_cases() -> dict[str, dict]:
    return {case["id"]: case for case in load_document()["cases"]}


def fixture_policy() -> RouterPolicy:
    policy = build_default_policy()
    for metric_id, values in load_document()["policy_overrides"].items():
        policy = policy.with_thresholds(metric_id, MetricThresholds(**values))
    return policy


def build_router(case: dict, policy: RouterPolicy | None = None) -> tuple[DecisionRouter, AlertEnvelope]:
    policy = policy or fixture_policy()
    envelope = AlertEnvelope.model_validate(case["envelope"])
    probe = DecisionRouter(
        policy,
        memory=InMemoryMemoryLedgerProvider(),
        similarity=InMemorySimilarityCaseProvider(),
        pattern_stats=InMemoryPatternStatsProvider(),
        playbooks=InMemoryPlaybookProvider(),
        route_store=InMemoryRouteStore(),
    )
    keys = probe.keys_for(envelope)
    state = case.get("state", {})
    memory = {keys.lineage_key: MemoryEntry.model_validate(state["memory"])} if "memory" in state else {}
    references = (
        {keys.lineage_key: [ReferenceCase.model_validate(state["reference"])]} if "reference" in state else {}
    )
    stats = {keys.pattern_key: PatternStats.model_validate(state["pattern_stats"])} if "pattern_stats" in state else {}
    playbooks = {keys.pattern_key: [Playbook.model_validate(state["playbook"])]} if "playbook" in state else {}
    router = DecisionRouter(
        policy,
        memory=InMemoryMemoryLedgerProvider(memory),
        similarity=InMemorySimilarityCaseProvider(references),
        pattern_stats=InMemoryPatternStatsProvider(stats),
        playbooks=InMemoryPlaybookProvider(playbooks),
        route_store=InMemoryRouteStore(),
    )
    return router, envelope
