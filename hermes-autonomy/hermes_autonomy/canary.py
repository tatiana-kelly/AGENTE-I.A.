"""Automação-canário (sandbox controlada) para provar DETECT → DIAGNOSE → REPAIR → VALIDATE → RECORD
sem tocar em nenhuma automação real. Tudo é escrito em <state_dir>/canary/.

Modos:
  ok                   execução completa (log + saída + "banco" + entrega)
  fail_once            1ª execução falha por timeout de rede (transitório); as seguintes funcionam
  fail_always          sempre falha com HTTP 503 (transitório, mas persistente)
  credential_missing   falha por credencial ausente (não transitório → escalar com ação)
  partial              gera saída, mas não atualiza o "banco"

Uso: python -m hermes_autonomy.canary run|set-mode <modo> [--state-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import default_state_dir

MODES = ("ok", "fail_once", "fail_always", "credential_missing", "partial")


def _dirs(state_dir: Path) -> dict[str, Path]:
    root = state_dir / "canary"
    paths = {"root": root, "logs": root / "logs", "output": root / "output", "data": root / "data"}
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def set_mode(state_dir: Path, mode: str) -> None:
    if mode not in MODES:
        raise SystemExit(f"modo inválido: {mode} (use {', '.join(MODES)})")
    paths = _dirs(state_dir)
    (paths["root"] / "mode.json").write_text(json.dumps({"mode": mode, "fails_remaining": 1}), encoding="utf-8")


def run(state_dir: Path) -> int:
    paths = _dirs(state_dir)
    mode_file = paths["root"] / "mode.json"
    state = json.loads(mode_file.read_text(encoding="utf-8")) if mode_file.exists() else {"mode": "ok"}
    now = datetime.now()
    log = paths["logs"] / f"canary_{now:%Y%m%d}.log"

    def write(level: str, message: str) -> None:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {level:<8} | {message}\n")

    write("INFO", "=== inicio canary ===")
    mode = state["mode"]
    if mode == "fail_once" and state.get("fails_remaining", 0) > 0:
        state["fails_remaining"] -= 1
        mode_file.write_text(json.dumps(state), encoding="utf-8")
        write("ERROR", "sb_select canary_source: <urlopen error [WinError 10060] timed out>")
        return 1
    if mode == "fail_always":
        write("ERROR", "POST /rest/v1/canary: HTTP Error 503: Service Unavailable")
        return 1
    if mode == "credential_missing":
        write("ERROR", "variável CANARY_API_TOKEN não definida — abortando")
        return 2
    (paths["output"] / f"canary_{now:%Y%m%d}.json").write_text(
        json.dumps({"generated_at": now.isoformat(), "rows": 42}), encoding="utf-8")
    write("INFO", "saida gerada: 42 linhas")
    if mode != "partial":
        (paths["data"] / "canary_table.json").write_text(
            json.dumps([{"updated_at": now.astimezone().isoformat()}]), encoding="utf-8")
        write("INFO", "banco atualizado: canary_table")
        write("INFO", "entrega: enviado (simulado)")
        write("INFO", "=== fim ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes_autonomy.canary")
    parser.add_argument("command", choices=["run", "set-mode"])
    parser.add_argument("mode", nargs="?")
    parser.add_argument("--state-dir")
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir) if args.state_dir else default_state_dir()
    if args.command == "set-mode":
        set_mode(state_dir, args.mode or "ok")
        return 0
    return run(state_dir)


if __name__ == "__main__":
    sys.exit(main())
