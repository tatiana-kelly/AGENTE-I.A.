"""Garantias da Fase 1: nenhuma chamada de IA, nenhum agente carregado, nenhum efeito externo."""

import ast
import builtins
import socket
from pathlib import Path

import pytest

from app.services import agent_loader, claude_client
from tests.fixtures.decision_router_loader import build_router, load_cases

CASES = load_cases()
ROUTER_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "decision_router"
FORBIDDEN_IMPORTS = {"anthropic", "openai", "httpx", "requests", "urllib", "socket", "sqlalchemy", "subprocess",
                     "app.services.claude_client", "app.services.orchestrator", "app.db"}


def test_router_package_imports_no_ai_network_or_database_modules():
    for path in ROUTER_PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_IMPORTS), (
                    f"{path.name} importa {name}"
                )


@pytest.fixture()
def no_side_effects(monkeypatch):
    def _deny_network(*_args, **_kwargs):
        raise AssertionError("Router tentou acessar a rede")

    real_open = builtins.open

    def _read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"Router tentou escrever em {file}")
        return real_open(file, mode, *args, **kwargs)

    def _deny_ai(*_args, **_kwargs):
        raise AssertionError("Router tentou instanciar cliente de IA")

    def _deny_agent(*_args, **_kwargs):
        raise AssertionError("Router tentou carregar prompt de agente")

    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(builtins, "open", _read_only_open)
    monkeypatch.setattr(claude_client.ClaudeClient, "__init__", _deny_ai)
    monkeypatch.setattr(agent_loader, "load_agent", _deny_agent)


def test_all_fixtures_run_without_ai_network_writes_or_agent_prompts(no_side_effects):
    ai_calls = 0
    for case in CASES.values():
        if "replay_of" in case:
            continue
        router, envelope = build_router(case)
        route = router.route(envelope)
        ai_calls += router.ai_calls_made
        assert route.contract_version == "sal.decision-route/1.0"
    assert ai_calls == 0


def test_router_never_creates_decision_or_action_records(no_side_effects):
    for case in CASES.values():
        if "replay_of" in case:
            continue
        router, envelope = build_router(case)
        route = router.route(envelope)
        assert route.next_step.action in {
            "close_case", "monitor", "propose_decision", "run_agents", "collect_evidence", "await_human"
        }
        if route.next_step.action == "propose_decision":
            assert route.requires_human_approval


def test_loop_guard_escalates_on_hop_limit():
    case = CASES["F05"]
    router, envelope = build_router(case)
    envelope = envelope.model_copy(update={"loop": envelope.loop.model_copy(update={"hop": 4})})
    route = router.route(envelope)
    assert route.status == "ESCALATED"
    assert route.route == "INVESTIGATE_FIRST" and route.selected_agents == ()
    assert route.requires_human_approval and route.next_step.action == "await_human"
