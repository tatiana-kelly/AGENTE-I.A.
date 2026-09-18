"""Configuração: defaults seguros (DRY_RUN=true) + arquivo JSON + variáveis de ambiente."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # hermes-autonomy/

DEFAULTS: dict[str, Any] = {
    "dry_run": True,
    "autonomous_repair": False,
    "max_repair_attempts": 3,
    "max_repair_risk": "low",
    "repair_window_hours": 6,
    "validation": {"poll_seconds": 15, "timeout_seconds": 1800, "settle_seconds": 5},
    "retry_backoff_seconds": [0, 60, 180],
    "circuit_breaker": {"failure_threshold": 5, "window_hours": 24, "cooldown_hours": 6},
    "rate_limits": {
        "repairs_per_hour": 10,
        "repairs_per_automation_per_day": 6,
        "notifications_per_hour": 6,
        "http_calls_per_run": 60,
    },
    "defaults": {"grace_minutes": 20, "delay_tolerance_minutes": 10, "max_duration_minutes": 60},
    "notification": {
        "channels": ["terminal", "outbox"],
        "external_enabled": False,
        "immediate_min_priority": "P1",
        "email_agent": {"path": "C:\\CENTRO-DE-AGENTES-IA", "recipient": None},
        "dedupe_hours": 12,
    },
    "report": {"title": "HERMES AUTOMATION HEALTH"},
}

_ENV_BOOL = {
    "HERMES_AUTONOMY_DRY_RUN": "dry_run",
    "DRY_RUN": "dry_run",
    "HERMES_AUTONOMY_AUTONOMOUS_REPAIR": "autonomous_repair",
    "AUTONOMOUS_REPAIR": "autonomous_repair",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "sim", "on")


def default_state_dir() -> Path:
    env = os.environ.get("HERMES_AUTONOMY_HOME")
    if env:
        return Path(env)
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / "autonomy"
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "hermes").exists():
        return Path(local) / "hermes" / "autonomy"
    return Path.home() / ".hermes" / "autonomy"


@dataclass
class Settings:
    data: dict[str, Any]
    state_dir: Path
    registry_path: Path

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @property
    def dry_run(self) -> bool:
        return bool(self.data["dry_run"])

    @property
    def autonomous_repair(self) -> bool:
        return bool(self.data["autonomous_repair"])

    @property
    def live_repairs_enabled(self) -> bool:
        """Correção real só com DRY_RUN=false E AUTONOMOUS_REPAIR=true."""
        return (not self.dry_run) and self.autonomous_repair


def load_settings(
    config_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    state_dir: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    data = deepcopy(DEFAULTS)
    candidates = [config_path] if config_path else [
        os.environ.get("HERMES_AUTONOMY_CONFIG"),
        PACKAGE_ROOT / "config" / "autonomy.json",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            data = _deep_merge(data, json.loads(Path(candidate).read_text(encoding="utf-8")))
            break
    for env_name, key in _ENV_BOOL.items():
        if env_name in os.environ:
            data[key] = _as_bool(os.environ[env_name])
    if overrides:
        data = _deep_merge(data, overrides)
    state = Path(state_dir) if state_dir else default_state_dir()
    registry = Path(
        registry_path
        or os.environ.get("HERMES_AUTONOMY_REGISTRY")
        or PACKAGE_ROOT / "registry" / "automations.json"
    )
    return Settings(data=data, state_dir=state, registry_path=registry)
