"""Fase 3 — memória do Decision Router: repositório, idempotência, reuso, playbooks, isolamento e shadow.

Base: recorte real de transferências (fixture) + cópia "dia anterior" criada em tmp_path. Nenhum banco é usado.
"""

import ast
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.decision_router.adapters import TorreDataReader, TransferInvestigationAdapter
from app.decision_router.memory.knowledge import classify_ledger_entry, classify_transfer_route
from app.decision_router.memory.postgres import PostgresCaseMemoryRepository, validate_database_url
from app.decision_router.memory.providers import (
    MemoryPatternStatsProvider,
    MemoryPlaybookProvider,
    MemorySimilarityCaseProvider,
    playbook_for_router,
)
from app.decision_router.memory.recorder import MemoryMode, MemoryRecorder, RepositoryRouteStore
from app.decision_router.memory.records import PlaybookRecord
from app.decision_router.memory.repository import (
    InMemoryCaseMemoryRepository,
    MemoryWriteBlocked,
    ReadOnlyCaseMemoryRepository,
)
from app.decision_router.memory.shadow_memory import (
    PinnedTorreReader,
    economy_report,
    run_memory_shadow,
    write_memory_report,
)
from app.decision_router.policy import build_default_policy
from app.decision_router.providers import InMemoryMemoryLedgerProvider
from app.decision_router.router import DecisionRouter

BACKEND = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND / "tests" / "fixtures" / "decision_router_shadow" / "torre_data"
MEMORY_CODE = BACKEND / "app" / "decision_router" / "memory"
SQL = MEMORY_CODE / "sql" / "001_decision_router_memory.sql"
TRANSFERS = "transferencias_investigacao"
ROUTE = "CARIACICA→VARGINHA"
RULES = "rules:test"
POLICY = build_default_policy()


def _torre(tmp_path: Path, day_changes: dict | None = None) -> Path:
    """Copia o recorte real e cria o dia anterior (2026-09-16) com o mesmo conteúdo, opcionalmente alterado."""
    data = tmp_path / "torre_data"
    shutil.copytree(FIXTURE, data)
    document = json.loads((data / TRANSFERS / "2026-09-17.json").read_text(encoding="utf-8"))
    previous = json.loads(json.dumps(document))
    previous["gerado_em"] = "2026-09-16T10:20:04"
    previous["dia_foco"] = "2026-09-16"
    for item in previous["rotas"]:
        for key, value in (day_changes or {}).get(item["rota"], {}).items():
            if key == "ocup":
                item["periodo_analisado"]["janela_5du"]["ocup"] = value
            else:
                item[key] = value
    (data / TRANSFERS / "2026-09-16.json").write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
    return data


def _alerts(data: Path, day: str, rules: str = RULES):
    reader = PinnedTorreReader(data, {TRANSFERS: f"{TRANSFERS}/{day}.json"})
    return {item.envelope.entity_id: item for item in TransferInvestigationAdapter().adapt(reader, rules).alerts}


def _router(repository):
    return DecisionRouter(
        POLICY, memory=InMemoryMemoryLedgerProvider(), similarity=MemorySimilarityCaseProvider(repository),
        pattern_stats=MemoryPatternStatsProvider(repository), playbooks=MemoryPlaybookProvider(repository),
        route_store=RepositoryRouteStore(repository),
    )


def _seed(tmp_path, day_changes=None, rules_previous=RULES):
    data = _torre(tmp_path, day_changes)
    repository = InMemoryCaseMemoryRepository()
    recorder = MemoryRecorder(POLICY, repository, MemoryMode.SHADOW_SIMULATED_PERSISTENCE)
    router = _router(repository)
    previous = _alerts(data, "2026-09-16", rules_previous)[ROUTE]
    route = router.route(previous.envelope)
    case = recorder.record(previous, route)
    return data, repository, recorder, case


def _human(repository, case, **fields):
    """Simula o fluxo humano existente registrando decisão/ação/verificação (o Router nunca faz isso)."""
    defaults = {
        "decision_id": "dec-1", "decision_status": "approved", "approved_at": datetime(2026, 9, 16, 12, tzinfo=UTC),
        "diagnosis_confidence": 90.0, "diagnosis_status": "READY_FOR_DECISION",
        "hypotheses": ({"status": "confirmed"},), "action_id": "act-1", "action_status": "completed",
        "verification_status": "ok", "recurrence": False, "learning_id": "learn-1",
        "learning_predicted_impact": 100.0, "learning_actual_impact": 100.0,
    }
    updated = case.model_copy(update={**defaults, **fields})
    repository._cases[case.exact_fingerprint] = updated
    return updated


def _today(data, repository, rules=RULES):
    return _router(repository).route(_alerts(data, "2026-09-17", rules)[ROUTE].envelope)


def _gate(route, name):
    return next(entry for entry in route.gate_trace if entry.gate == name)


# 1–4 ─ repositório e idempotência ───────────────────────────────────────────────────────────

def test_01_insert_case(tmp_path):
    _, repository, recorder, case = _seed(tmp_path)
    assert recorder.inserted == 1 and len(repository.all_cases()) == 1
    assert case.decision_status == "none" and case.action_status == "none" and case.verification_status == "none"
    assert case.route_payload is not None


def test_02_find_by_exact_fingerprint(tmp_path):
    _, repository, _, case = _seed(tmp_path)
    assert repository.get_by_exact(case.exact_fingerprint) == case
    assert repository.get_by_exact("sha256:" + "0" * 64) is None


def test_03_find_by_pattern_key(tmp_path):
    data, repository, recorder, case = _seed(tmp_path)
    today = _alerts(data, "2026-09-17")[ROUTE]
    recorder.record(today, _router(repository).route(today.envelope))
    assert [item.period for item in repository.list_by_pattern(case.pattern_key)] == ["5du:2026-09-16", "5du:2026-09-17"]


def test_04_idempotency_runs_1_2_3(tmp_path):
    data, repository, recorder, case = _seed(tmp_path)
    previous = _alerts(data, "2026-09-16")[ROUTE]
    for _ in (2, 3):
        router = _router(repository)
        route = router.route(previous.envelope)
        assert router.replays == 1 and router.evaluations == 0
        assert recorder.record(previous, route) == case
    assert recorder.inserted == 1 and recorder.duplicates == 2 and len(repository.all_cases()) == 1
    assert repository.get_pattern_stats(case.pattern_key).occurrences == 1


# 5–6 ─ caso novo / recorrente ───────────────────────────────────────────────────────────────

def test_05_new_case_has_no_reference(tmp_path):
    data = _torre(tmp_path)
    route = _router(InMemoryCaseMemoryRepository()).route(_alerts(data, "2026-09-17")[ROUTE].envelope)
    assert route.similarity_reference is None
    assert route.route == "MULTI_AGENT"


def test_06_recurring_case_finds_previous_and_counts(tmp_path):
    data, repository, recorder, case = _seed(tmp_path)
    today = _alerts(data, "2026-09-17")[ROUTE]
    route = _router(repository).route(today.envelope)
    recorder.record(today, route)
    assert route.similarity_reference.case_id == case.id
    assert route.similarity_reference.material_change is False
    assert route.route == "MULTI_AGENT"  # recorrente sem decisão aprovada continua investigando
    assert repository.get_pattern_stats(case.pattern_key).occurrences == 2


# 7–12 ─ decisão, resultado, reincidência, reabertura ────────────────────────────────────────

def test_07_approved_decision_without_verification_is_not_reusable(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, verification_status="none", action_status="completed")
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "ação anterior sem outcome ok" in _gate(route, "decision").reason


def test_08_proposed_decision_is_not_approved(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, decision_status="proposed", approved_at=None)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "decisão anterior não aprovada" in _gate(route, "decision").reason


def test_09_verified_ok_result_enables_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case)
    assert _today(data, repository).route == "REUSE_DECISION"


def test_10_verified_fail_result_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, verification_status="fail")
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "outcome ok (fail)" in _gate(route, "decision").reason


def test_11_recurrence_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, recurrence=True)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "recorrência não descartada" in _gate(route, "decision").reason


def test_12_reopened_reference_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, reopen_count=1)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "caso reaberto" in _gate(route, "decision").reason


# 13–16 ─ bloqueios estruturais ──────────────────────────────────────────────────────────────

def test_13_different_rules_version_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path, rules_previous="rules:old")
    _human(repository, case)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "rules_version" in route.similarity_reference.material_change_reasons


def test_14_material_change_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path, {ROUTE: {"ocup": 60.0, "ocupacao": "MODERADA"}})
    _human(repository, case)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "material_change" in _gate(route, "decision").reason
    # a faixa entra no pattern_key: faixa diferente = padrão diferente, mas a linhagem ainda acha o caso
    assert route.similarity_reference.material_change is True
    assert "magnitude_band" in route.similarity_reference.material_change_reasons


def test_15_missing_magnitude_band_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case)
    policy = POLICY.metric("ocupacao-transferencia")
    no_classes = type(policy)(**{**policy.__dict__, "engine_classes": {}})
    missing_policy = POLICY.__class__(**{**POLICY.__dict__,
                                         "metrics": {**POLICY.metrics, "ocupacao-transferencia": no_classes}})
    router = DecisionRouter(
        missing_policy, memory=InMemoryMemoryLedgerProvider(), similarity=MemorySimilarityCaseProvider(repository),
        pattern_stats=MemoryPatternStatsProvider(repository), playbooks=MemoryPlaybookProvider(repository),
        route_store=RepositoryRouteStore(repository),
    )
    route = router.route(_alerts(data, "2026-09-17")[ROUTE].envelope)
    assert route.route != "REUSE_DECISION"
    assert "magnitude_band MISSING" in _gate(route, "decision").reason


def test_16_learning_veto_blocks_reuse(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case)
    stats = repository.get_pattern_stats(case.pattern_key)
    repository.save_pattern_stats(stats.model_copy(update={"reuse_verified_fail": 1}))
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert _gate(route, "learning").result == "blocked"


# 17–20 ─ candidato, rejeição, playbooks ─────────────────────────────────────────────────────

def test_17_reuse_candidate_is_only_a_proposal(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case)
    route = _today(data, repository)
    assert route.route == "REUSE_DECISION"
    assert route.reused_decision_id == "dec-1"
    assert route.requires_human_approval is True
    assert route.next_step.action == "propose_decision"
    assert route.estimated_ai_calls == 0 and route.selected_agents == ()
    # a memória não ganhou decisão nova: o Router não grava decisão nem ação
    assert all(item.decision_id in (None, "dec-1") for item in repository.all_cases())


def test_18_rejected_candidate_is_not_reused(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    _human(repository, case, decision_status="rejected", approved_at=None)
    route = _today(data, repository)
    assert route.route != "REUSE_DECISION"
    assert "decisão anterior não aprovada" in _gate(route, "decision").reason


def _playbook(case, **fields):
    now = datetime(2026, 9, 16, tzinfo=UTC)
    base = {"id": "pb-1", "pattern_key": case.pattern_key, "case_type": "transfer", "name": "teste",
            "conditions": {}, "recommended_action": {}, "rules_version": RULES, "magnitude_band": case.magnitude_band,
            "status": "draft", "created_at": now, "updated_at": now, "valid_from": now}
    return PlaybookRecord(**{**base, **fields})


def test_19_inactive_playbook_does_not_apply(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    repository.save_playbook(_playbook(case, status="draft"))
    route = _today(data, repository)
    assert route.playbook is None
    assert _gate(route, "playbook").result != "resolved"


def test_20_playbook_without_human_approval_never_active(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    unapproved = _playbook(case, status="active")
    with pytest.raises(MemoryWriteBlocked):
        repository.save_playbook(unapproved)
    assert playbook_for_router(unapproved).status == "pending_approval"
    # ocorrências repetidas não criam playbook
    today = _alerts(data, "2026-09-17")[ROUTE]
    MemoryRecorder(POLICY, repository, MemoryMode.SHADOW_SIMULATED_PERSISTENCE).record(
        today, _router(repository).route(today.envelope))
    assert repository.get_current_playbook(case.pattern_key) is None


# 21 ─ RLS / isolamento ──────────────────────────────────────────────────────────────────────

def test_21_rls_and_isolation():
    sql = SQL.read_text(encoding="utf-8").lower()
    # aplicada em 2026-09-17 apenas no destino autorizado; o arquivo registra projeto e schema
    assert "sal-ai-orchestrator" in sql and "zkwfupxztxczeadrlsri" in sql
    assert "shadow_read_only" in sql  # o banco não recebe casos automaticamente nesta fase
    for other in ("relatorios-raw", "pendency-tracker", "command deck"):
        assert f"não aplicar em {other}" in sql or other in sql.split("não aplicar em", 1)[1].split("\n")[0]
    for table in ("case_routes", "pattern_stats", "playbooks"):
        assert f"alter table decision_router.{table}" in sql and "enable row level security" in sql
    assert "revoke all on all tables in schema decision_router from anon, authenticated" in sql
    assert "grant" not in sql and "service_role" not in sql.replace("não usar service_role", "")
    assert "create policy" not in sql  # negado por padrão até a política do projeto aprovado
    assert "unique (exact_fingerprint)" in sql
    assert "playbooks_active_requires_human_approval" in sql
    for statement in sql.split(";"):
        body = "\n".join(line for line in statement.splitlines() if not line.strip().startswith("--"))
        for word in ("create table", "create index", "alter table"):
            if word in body:
                assert "decision_router." in body
    for other in ("public.", "relatorios", "pendency", "ai_tasks"):
        assert other not in "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    with pytest.raises(ValueError):
        validate_database_url("sqlite:///memoria.db")
    with pytest.raises(ValueError):
        PostgresCaseMemoryRepository("sqlite:///memoria.db")
    read_only = ReadOnlyCaseMemoryRepository(InMemoryCaseMemoryRepository())
    with pytest.raises(MemoryWriteBlocked):
        read_only.save_pattern_stats(None)


# 22 ─ shadow sem efeito externo ─────────────────────────────────────────────────────────────

FORBIDDEN = {"anthropic", "openai", "google", "httpx", "requests", "urllib", "socket", "smtplib", "email",
             "subprocess", "supabase", "app.api", "app.models", "app.services.claude_client",
             "app.services.orchestrator"}


def test_22_shadow_with_memory_has_no_external_effects(tmp_path, monkeypatch):
    import builtins
    import socket
    import subprocess

    from app.services import agent_loader, claude_client

    for path in MEMORY_CODE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        for marker in ("/v1/agent-runs", "/orchestrate", "ActionExecution", "whatsapp", "send_email"):
            assert marker not in text, f"{path.name}: {marker}"
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for name in names:
                assert not any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN), f"{path.name}: {name}"
                if path.name != "postgres.py":
                    assert not name.startswith(("sqlalchemy", "psycopg", "app.decision_router.memory.postgres"))

    data = _torre(tmp_path)
    before = {path: path.read_bytes() for path in data.rglob("*") if path.is_file()}
    output = tmp_path / "out"

    def deny(*_args, **_kwargs):
        raise AssertionError("efeito externo proibido")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")) and not str(file).startswith(str(output)):
            raise AssertionError(f"escrita fora do relatório: {file}")
        return real_open(file, mode, *args, **kwargs)

    real_write_text = Path.write_text

    def guarded_write_text(self, *args, **kwargs):
        if not str(self).startswith(str(output)):
            raise AssertionError(f"escrita fora do relatório: {self}")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(subprocess, "run", deny)
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    monkeypatch.setattr(claude_client.ClaudeClient, "__init__", deny)
    monkeypatch.setattr(agent_loader, "load_agent", deny)

    run = run_memory_shadow(data, mode=MemoryMode.SHADOW_SIMULATED_PERSISTENCE, run_id="sealed")
    target = write_memory_report(run, output)
    report = economy_report(run)
    assert report["ai_calls_actual"] == 0 and report["persistent_writes"] == 0
    assert all(item["ai_calls_actual"] == 0 and item["external_effects"] == 0 for item in run.with_memory.results)
    assert target.parent == output
    assert {path: path.read_bytes() for path in data.rglob("*") if path.is_file()} == before


# complementares ─────────────────────────────────────────────────────────────────────────────

def test_shadow_read_only_does_not_mutate_memory(tmp_path):
    data, repository, _, case = _seed(tmp_path)
    stats_before = repository.get_pattern_stats(case.pattern_key)
    recorder = MemoryRecorder(POLICY, repository, MemoryMode.SHADOW_READ_ONLY)
    today = _alerts(data, "2026-09-17")[ROUTE]
    recorder.record(today, _router(repository).route(today.envelope))
    assert recorder.inserted == 0 and recorder.skipped_read_only == 1
    assert len(repository.all_cases()) == 1
    assert repository.get_pattern_stats(case.pattern_key) == stats_before


def test_persist_mode_requires_explicit_enable_and_simulation_requires_memory_repo():
    with pytest.raises(MemoryWriteBlocked):
        MemoryRecorder(POLICY, InMemoryCaseMemoryRepository(), MemoryMode.PERSIST)
    with pytest.raises(MemoryWriteBlocked):
        MemoryRecorder(POLICY, ReadOnlyCaseMemoryRepository(InMemoryCaseMemoryRepository()),
                       MemoryMode.SHADOW_SIMULATED_PERSISTENCE)
    with pytest.raises(ValueError):
        run_memory_shadow(FIXTURE, mode=MemoryMode.PERSIST)


def test_economy_report_fields_and_honest_zero_reuse(tmp_path):
    data = _torre(tmp_path)
    report = economy_report(run_memory_shadow(data, mode=MemoryMode.SHADOW_SIMULATED_PERSISTENCE, run_id="eco"))
    for key in ("baseline_calls", "router_without_memory_calls", "router_with_memory_calls",
                "estimated_ai_calls_avoided_by_routing", "estimated_ai_calls_avoided_by_memory", "reuse_candidates",
                "reuse_blocked_by_material_change", "reuse_blocked_by_missing_band", "reuse_blocked_by_no_approval",
                "reuse_blocked_by_learning", "unknown_cases", "blocked_quality"):
        assert key in report
    assert report["reuse_candidates"] == 0 and report["estimated_ai_calls_avoided_by_memory"] == 0
    assert report["reuse_blocked_by_no_approval"] == report["alerts_with_previous_case_reaching_decision_gate"] > 0
    assert report["idempotency"]["reruns"] == [
        {"run": 2, "inserted": 0, "duplicates_ignored": report["alerts_processed"]},
        {"run": 3, "inserted": 0, "duplicates_ignored": report["alerts_processed"]},
    ]
    assert "usd" not in json.dumps(report).lower()


def test_learning_record_is_never_promoted_to_decision():
    reader = TorreDataReader(FIXTURE)
    from app.decision_router.adapters import ledger_memory_entries

    entries, _ = ledger_memory_entries(reader)
    assert entries
    for entry in entries.values():
        status = classify_ledger_entry(entry)
        assert status.known and not status.decision_known and not status.decision_approved and not status.result_known
    route = {"status": "AGUARDANDO_VALIDACAO_HUMANA", "feedback_humano": None}
    status = classify_transfer_route(route, {"total": 0})
    assert not status.decision_known and not status.decision_approved and not status.result_known
