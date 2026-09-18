"""Adaptadores read-only sobre recortes das estruturas reais da Torre (tests/fixtures/decision_router_shadow)."""

from pathlib import Path

from app.decision_router.adapters import (
    ApuracaoCardDivergenceAdapter,
    CostPerCteAdapter,
    CostPerformanceAdapter,
    DeficitClientsAdapter,
    ProjectionAlertAdapter,
    ReconciliationTorreApuracaoAdapter,
    SswBiRouteDivergenceAdapter,
    TorreDataReader,
    TransferInvestigationAdapter,
    ledger_memory_entries,
)
from app.decision_router.adapters.base import parse_torre_timestamp, pseudonymize
from app.decision_router.inputs import AlertEnvelope

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "decision_router_shadow" / "torre_data"
READER = TorreDataReader(DATA)
RULES = "rules:test"


def _check_envelopes(output) -> None:
    for adapted in output.alerts:
        assert AlertEnvelope.model_validate(adapted.envelope.model_dump()) == adapted.envelope
        assert adapted.transformations, "toda transformação deve ser rastreável"
        assert adapted.envelope.rules_version == RULES
        assert adapted.envelope.evaluated_at.tzinfo is not None


def test_ssw_bi_divergence_adapter_uses_engine_delta():
    raw = READER.read_json("divergencia_rota_ssw_bi.json")["rotas_divergentes"]
    output = SswBiRouteDivergenceAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    assert len(output.alerts) == len(raw)
    for adapted, item in zip(output.alerts, raw, strict=True):
        alert = adapted.envelope.alert
        assert adapted.envelope.entity_id == item["rota"]
        assert round(alert.current_value - alert.reference_value, 2) == round(item["delta"], 2)
        assert alert.materiality == abs(item["delta"])


def test_ledger_memory_mirrors_real_learning_registry():
    entries, notes = ledger_memory_entries(READER)
    ledger = READER.read_json("aprendizado_agentes.json")
    assert set(entries) == set(ledger["estado_atual"])
    for route, entry in entries.items():
        state = ledger["estado_atual"][route]
        assert entry.status == state["status"] and entry.causa == state["causa"] and entry.delta == state["delta"]
        assert entry.magnitude_band == "MISSING"
    assert "0 com causa registrada" in notes[0]


def test_card_divergence_adapter_has_no_concentration():
    output = ApuracaoCardDivergenceAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    registry = READER.read_json("apuracao_alertas_enviados.json")["alertas"]
    assert len(output.alerts) == len(registry)
    assert all(adapted.envelope.alert.concentration == [] for adapted in output.alerts)


def test_reconciliation_adapter_keeps_only_engine_investigar_lines():
    lines = READER.read_json("reconciliacao_torre_apuracao.json")["linhas"]
    output = ReconciliationTorreApuracaoAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    assert len(output.alerts) == sum(1 for line in lines if line["classificacao"] == "INVESTIGAR")
    assert len(output.skipped) == len(lines) - len(output.alerts)
    for adapted in output.alerts:
        inputs = adapted.envelope.quality_inputs
        assert inputs is not None and inputs.current_grain and inputs.reference_grain


def test_transfer_adapter_uses_engine_priority_and_window():
    document = READER.read_json("transferencias_investigacao/2026-09-17.json")
    output = TransferInvestigationAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    prioritized = [route for route in document["rotas"] if route["prioridade"] != "NORMAL"]
    assert len(output.alerts) == len(prioritized)
    assert len(output.skipped) == len(document["rotas"]) - len(prioritized)
    full = READER.read_json("config_investigador.json")["ocupacao_cheio"]
    for adapted, route in zip(output.alerts, prioritized, strict=True):
        assert adapted.envelope.alert.current_value == route["periodo_analisado"]["janela_5du"]["ocup"]
        assert adapted.envelope.alert.reference_value == full
        assert adapted.envelope.signals.window_class == route["ocupacao"]


def test_cost_per_cte_adapter_uses_engine_flag_and_coverage_rule():
    rows = READER.read_json("latest.json")["diagnosticos_operacionais"]["custo_performance"]["dados"]
    output = CostPerCteAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    assert {adapted.envelope.entity_id for adapted in output.alerts} == {r["sigla"] for r in rows if r["acima_alerta_cte"]}
    expected_coverage = round(100 * sum(1 for r in rows if r["custo"] > 0 and r["qtd_ctes"] > 0) / len(rows), 2)
    assert all(adapted.envelope.signals.coverage_pct == expected_coverage for adapted in output.alerts)


def test_cost_performance_adapter_marks_missing_kpi_as_insufficient():
    rows = READER.read_json("latest.json")["diagnosticos_operacionais"]["custo_performance"]["dados"]
    output = CostPerformanceAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    by_base = {adapted.envelope.entity_id: adapted.envelope for adapted in output.alerts}
    for row in rows:
        if row["categoria"] == "OK":
            assert row["sigla"] not in by_base
            continue
        expected = "real" if row["kpi_performance"] else "insufficient"
        assert by_base[row["sigla"]].alert.source_quality == expected
        assert by_base[row["sigla"]].signals.category == row["categoria"]


def test_projection_adapter_reads_executive_alerts():
    document = READER.read_json("projecao_fatxcustos_latest.json")
    output = ProjectionAlertAdapter().adapt(READER, RULES)
    _check_envelopes(output)
    assert len(output.alerts) == len(document["alertas_executivos"])
    assert output.alerts[0].envelope.alert.current_value == document["bases"][0]["aceleracao_pct"]


def test_deficit_clients_adapter_emits_nothing_when_engine_list_is_empty():
    output = DeficitClientsAdapter().adapt(READER, RULES)
    assert output.alerts == ()
    assert any("quase_la não é alerta" in note for note in output.notes)


def test_missing_source_file_is_reported_not_invented(tmp_path):
    output = SswBiRouteDivergenceAdapter().adapt(TorreDataReader(tmp_path), RULES)
    assert output.alerts == () and "arquivo não encontrado" in output.notes[0]


def test_helpers_are_deterministic():
    assert pseudonymize("Cliente X ") == pseudonymize("CLIENTE X")
    assert parse_torre_timestamp("2026-09-17T14:03:08").utcoffset().total_seconds() == -3 * 3600
