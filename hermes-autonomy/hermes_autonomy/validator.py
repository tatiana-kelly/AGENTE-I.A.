"""hermes-validator — nunca confia no retorno do Reparador: reexecuta a verificação completa
(EXPECTED vs ACTUAL) sobre a execução disparada pelo reparo."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from .models import CheckResult, CheckStatus, IncidentType, now_local

AGENT = "hermes-validator"


class Validator:
    def __init__(self, settings, guardian, clock: Callable[[], datetime] = now_local,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.guardian = guardian
        self.clock = clock
        self.sleep = sleep

    def validate(self, automation: dict[str, Any], since: datetime,
                 baseline: dict[str, tuple[int, float]] | None = None) -> CheckResult:
        cfg = self.settings["validation"]
        self.sleep(cfg["settle_seconds"])
        deadline = self.clock().timestamp() + min(
            cfg["timeout_seconds"], int(automation.get("max_duration_minutes", 60)) * 60 + 120)
        provider = self.guardian.providers.get(automation["source"])
        while True:
            if hasattr(provider, "refresh"):
                provider.refresh()
            result = self.guardian.evaluate(automation, now=self.clock(), run_after=since, baseline=baseline)
            waiting = result.status == CheckStatus.PENDING.value or (
                result.incident_type == IncidentType.MISSED_EXECUTION.value and automation["source"] != "command")
            if not waiting or self.clock().timestamp() >= deadline:
                return result
            self.sleep(cfg["poll_seconds"])
