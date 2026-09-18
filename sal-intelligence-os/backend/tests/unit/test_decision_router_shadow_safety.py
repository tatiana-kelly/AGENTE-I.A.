"""Segurança do shadow mode: zero IA, zero rede, zero escrita fora do relatório, zero subprocesso."""

import ast
import builtins
import socket
import subprocess
from pathlib import Path

import pytest

from app.decision_router import shadow_runner
from app.services import agent_loader, claude_client

BACKEND = Path(__file__).resolve().parents[2]
DATA = BACKEND / "tests" / "fixtures" / "decision_router_shadow" / "torre_data"
SHADOW_CODE = [*(BACKEND / "app" / "decision_router" / "adapters").glob("*.py"),
               BACKEND / "app" / "decision_router" / "shadow_runner.py"]
FORBIDDEN = {
    "anthropic", "openai", "google", "httpx", "requests", "urllib", "socket", "smtplib", "email", "subprocess",
    "supabase", "psycopg2", "sqlalchemy", "app.db", "app.api", "app.models", "app.services.claude_client",
    "app.services.orchestrator",
}


def test_shadow_code_imports_no_ai_network_mail_database_or_process_modules():
    for path in SHADOW_CODE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            )
            for name in names:
                assert not any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN), f"{path.name}: {name}"


def test_shadow_code_has_no_agent_runs_or_action_endpoints():
    for path in SHADOW_CODE:
        text = path.read_text(encoding="utf-8")
        for marker in ("/v1/agent-runs", "/orchestrate", "ActionExecution", "whatsapp", "send_email", "enviar_email"):
            assert marker not in text, f"{path.name} contém {marker}"


@pytest.fixture()
def sealed(monkeypatch, tmp_path):
    def deny(*_args, **_kwargs):
        raise AssertionError("efeito externo proibido")

    real_open = builtins.open
    allowed_root = str(tmp_path)

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")) and not str(file).startswith(allowed_root):
            raise AssertionError(f"escrita fora do relatório: {file}")
        return real_open(file, mode, *args, **kwargs)

    real_write_text = Path.write_text

    def guarded_write_text(self, *args, **kwargs):
        if not str(self).startswith(allowed_root):
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
    return tmp_path


def test_shadow_run_with_everything_sealed(sealed):
    run = shadow_runner.run_shadow(DATA, run_id="sealed")
    target = shadow_runner.write_report(run, sealed)
    summary = shadow_runner.summarize(run)
    assert summary["alerts_processed"] > 0
    assert summary["ai_calls_actual"] == 0
    assert summary["external_effects"] == 0
    assert all(item["ai_calls_actual"] == 0 and item["external_effects"] == 0 for item in run.results)
    assert target.parent == sealed


def test_cli_runs_sealed(sealed, capsys):
    assert shadow_runner.main(["--torre-data", str(DATA), "--output", str(sealed)]) == 0
    assert '"ai_calls_actual": 0' in capsys.readouterr().out
