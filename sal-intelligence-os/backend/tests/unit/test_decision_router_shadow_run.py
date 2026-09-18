"""Shadow run ponta a ponta sobre recortes reais: rotas, UNKNOWN, MISSING, qualidade, determinismo, relatório."""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.decision_router.shadow_runner import (
    agent_demand_report,
    data_quality_report,
    run_shadow,
    summarize,
    write_report,
)

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "decision_router_shadow" / "torre_data"
FIXED_AT = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


def _run(run_id: str = "test-run"):
    return run_shadow(DATA, run_id=run_id, started_at=FIXED_AT)


def _by_source(run):
    grouped = {}
    for item in run.results:
        grouped.setdefault(item["source"], []).append(item)
    return grouped


def test_real_routes_by_source():
    grouped = _by_source(_run())
    assert {item["route"] for item in grouped["torre.divergencia_rota_ssw_bi"]} == {"INVESTIGATE_FIRST"}
    assert {item["status"] for item in grouped["torre.conferir_apuracao_custo"]} == {"BLOCKED_DATA"}
    assert {item["status"] for item in grouped["torre.reconciliacao_torre_apuracao"]} == {"BLOCKED_DATA"}
    for item in grouped["torre.investigador_transferencias"]:
        assert item["route"] == "MULTI_AGENT"
        assert item["selected_agents"] == ["investigador", "transferencia"]
    for item in grouped["torre.motor_snapshot_painel:custo-por-cte-base"]:
        assert item["route"] == "MULTI_AGENT"
        assert item["selected_agents"] == ["investigador", "entrega", "custos-orcamento-roi"]
    assert {item["route"] for item in grouped["torre.orquestrador_projecao"]} == {"INVESTIGATE_FIRST"}


def test_divergence_is_pending_human_confirmation_even_with_real_memory():
    items = _by_source(_run())["torre.divergencia_rota_ssw_bi"]
    for item in items:
        assert item["case_type_resolution"] == "POLICY_PENDING_CONFIRMATION"
        assert item["next_step"]["action"] == "await_human"
        assert "memory:pass" in item["gate_trace"]  # registro real existe, mas sem causa registrada


def test_unknown_case_types_are_not_guessed():
    run = _run()
    resolutions = {item["metric_id"]: item["case_type_resolution"] for item in run.results}
    assert resolutions["projecao-faturamento-custos-base"] == "UNKNOWN_POLICY_PENDING"
    assert resolutions["reconciliacao-torre-apuracao"] == "UNKNOWN_NO_POLICY"
    for item in run.results:
        if item["case_type"] == "UNKNOWN":
            assert item["selected_agents"] == [] and item["estimated_ai_calls"] == 0


def test_missing_bands_are_preserved():
    run = _run()
    for item in run.results:
        if item["metric_id"] in {"divergencia-custo-rota-ssw-bi", "divergencia-card-apuracao-ssw",
                                 "projecao-faturamento-custos-base"}:
            assert item["magnitude_band"] == "MISSING"
        assert item["route"] != "REUSE_DECISION"


def test_insufficient_quality_blocks_ai():
    run = _run()
    blocked = [item for item in run.results if item["status"] == "BLOCKED_DATA"]
    assert blocked
    for item in blocked:
        assert item["quality"]["passed"] is False
        assert item["selected_agents"] == [] and item["estimated_ai_calls"] == 0
        assert item["estimated_ai_calls_avoided"] in (0, None)  # bloqueio não conta como economia
    reasons = Counter(reason for item in blocked for reason in item["quality"]["reasons"])
    assert any("concentration" in reason for reason in reasons)
    assert any("granularidade incomparável" in reason for reason in reasons)
    assert any("source_quality" in reason for reason in reasons)


def test_engine_band_matches_router_band_for_transfers():
    assert data_quality_report(_run())["engine_band_mismatch"] == []


def test_run_twice_same_routes_and_fingerprints():
    first, second = _run("a"), _run("b")
    keys = ("alert_id", "route", "status", "fingerprint_exact", "pattern_key", "lineage_key", "selected_agents",
            "gate_trace", "estimated_ai_calls")
    assert [{k: item[k] for k in keys} for item in first.results] == [{k: item[k] for k in keys} for item in second.results]


def test_summary_counts_are_consistent():
    run = _run()
    summary = summarize(run)
    assert summary["alerts_processed"] == len(run.results)
    assert sum(summary["routes"].values()) == summary["alerts_processed"]
    assert summary["ai_calls_actual"] == 0 and summary["external_effects"] == 0
    demand = agent_demand_report(run)
    assert sum(demand["agents"].values()) == sum(len(item["selected_agents"]) for item in run.results)


def test_report_files_are_written_only_to_output(tmp_path):
    before = {path: path.read_bytes() for path in DATA.rglob("*") if path.is_file()}
    run = _run()
    target = write_report(run, tmp_path)
    assert sorted(path.name for path in target.iterdir()) == [
        "agent_demand.json", "data_quality.json", "routes.jsonl", "summary.json"
    ]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
    lines = (target / "routes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(run.results)
    record = json.loads(lines[0])
    for field in ("run_id", "timestamp", "source", "alert_id", "metric_id", "case_type", "pattern_key",
                  "lineage_key", "route", "route_reason", "quality", "priority", "selected_agents",
                  "estimated_ai_calls", "ai_calls_actual", "external_effects"):
        assert field in record
    assert record["ai_calls_actual"] == 0 and record["external_effects"] == 0
    after = {path: path.read_bytes() for path in DATA.rglob("*") if path.is_file()}
    assert before == after, "a fonte não pode ser alterada"
