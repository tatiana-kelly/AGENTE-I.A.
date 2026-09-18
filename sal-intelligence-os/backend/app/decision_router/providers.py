"""Interfaces de estado consultado pelo Router + implementações em memória para testes.

Trocar por Supabase no futuro significa implementar os mesmos Protocols — o Router não muda.
"""

from datetime import datetime
from typing import Protocol

from app.decision_router.contract import DecisionRoute
from app.decision_router.inputs import MemoryEntry, PatternStats, Playbook, ReferenceCase


class MemoryLedgerProvider(Protocol):
    def get(self, lineage_key: str) -> MemoryEntry | None: ...


class SimilarityCaseProvider(Protocol):
    def find_reference(self, lineage_key: str, before: datetime) -> ReferenceCase | None: ...


class PatternStatsProvider(Protocol):
    def get(self, pattern_key: str) -> PatternStats | None: ...


class PlaybookProvider(Protocol):
    def get_current(self, pattern_key: str) -> Playbook | None: ...


class RouteStore(Protocol):
    def get_open(self, fingerprint_exact: str) -> DecisionRoute | None: ...

    def remember(self, route: DecisionRoute) -> None: ...


class InMemoryMemoryLedgerProvider:
    def __init__(self, entries: dict[str, MemoryEntry] | None = None) -> None:
        self._entries = dict(entries or {})

    def get(self, lineage_key: str) -> MemoryEntry | None:
        return self._entries.get(lineage_key)


class InMemorySimilarityCaseProvider:
    def __init__(self, cases: dict[str, list[ReferenceCase]] | None = None) -> None:
        self._cases = {key: list(value) for key, value in (cases or {}).items()}

    def find_reference(self, lineage_key: str, before: datetime) -> ReferenceCase | None:
        candidates = [case for case in self._cases.get(lineage_key, []) if case.evaluated_at < before]
        return max(candidates, key=lambda case: case.evaluated_at) if candidates else None


class InMemoryPatternStatsProvider:
    def __init__(self, stats: dict[str, PatternStats] | None = None) -> None:
        self._stats = dict(stats or {})

    def get(self, pattern_key: str) -> PatternStats | None:
        return self._stats.get(pattern_key)


class InMemoryPlaybookProvider:
    def __init__(self, playbooks: dict[str, list[Playbook]] | None = None) -> None:
        self._playbooks = {key: list(value) for key, value in (playbooks or {}).items()}

    def get_current(self, pattern_key: str) -> Playbook | None:
        versions = self._playbooks.get(pattern_key, [])
        return max(versions, key=lambda playbook: playbook.version) if versions else None


class InMemoryRouteStore:
    """Mantém rotas só na memória do processo (idempotência nos testes); não é persistência."""

    def __init__(self) -> None:
        self._routes: dict[str, DecisionRoute] = {}

    def get_open(self, fingerprint_exact: str) -> DecisionRoute | None:
        return self._routes.get(fingerprint_exact)

    def remember(self, route: DecisionRoute) -> None:
        self._routes.setdefault(route.fingerprints.exact, route)
