"""Repositório da memória do Router: interface + implementação em memória + guarda somente leitura.

A implementação Postgres/Supabase NÃO existe ainda: depende da decisão D4 (qual projeto Supabase hospeda o
SAL OS). Quando existir, basta implementar CaseMemoryRepository com a migration decision_router_memory.
"""

from datetime import datetime
from typing import Protocol

from app.decision_router.memory.records import CaseRecord, PatternStatsRecord, PlaybookRecord


class MemoryWriteBlocked(RuntimeError):
    """Escrita tentada em modo SHADOW_READ_ONLY."""


class CaseMemoryRepository(Protocol):
    def record_case(self, case: CaseRecord) -> tuple[CaseRecord, bool]: ...

    def get_by_exact(self, exact_fingerprint: str) -> CaseRecord | None: ...

    def list_by_pattern(self, pattern_key: str) -> list[CaseRecord]: ...

    def latest_by_lineage(self, lineage_key: str, before: datetime) -> CaseRecord | None: ...

    def get_pattern_stats(self, pattern_key: str) -> PatternStatsRecord | None: ...

    def save_pattern_stats(self, stats: PatternStatsRecord) -> None: ...

    def get_current_playbook(self, pattern_key: str) -> PlaybookRecord | None: ...

    def save_playbook(self, playbook: PlaybookRecord) -> None: ...


class InMemoryCaseMemoryRepository:
    """Simula a persistência: exact_fingerprint é único (mesma regra da constraint da migration)."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}
        self._stats: dict[str, PatternStatsRecord] = {}
        self._playbooks: dict[str, list[PlaybookRecord]] = {}
        self.writes = 0

    def record_case(self, case: CaseRecord) -> tuple[CaseRecord, bool]:
        existing = self._cases.get(case.exact_fingerprint)
        if existing is not None:
            return existing, False
        self._cases[case.exact_fingerprint] = case
        self.writes += 1
        return case, True

    def get_by_exact(self, exact_fingerprint: str) -> CaseRecord | None:
        return self._cases.get(exact_fingerprint)

    def list_by_pattern(self, pattern_key: str) -> list[CaseRecord]:
        return sorted((c for c in self._cases.values() if c.pattern_key == pattern_key), key=lambda c: c.observed_at)

    def latest_by_lineage(self, lineage_key: str, before: datetime) -> CaseRecord | None:
        candidates = [c for c in self._cases.values() if c.lineage_key == lineage_key and c.observed_at < before]
        return max(candidates, key=lambda c: c.observed_at) if candidates else None

    def get_pattern_stats(self, pattern_key: str) -> PatternStatsRecord | None:
        return self._stats.get(pattern_key)

    def save_pattern_stats(self, stats: PatternStatsRecord) -> None:
        self._stats[stats.pattern_key] = stats
        self.writes += 1

    def get_current_playbook(self, pattern_key: str) -> PlaybookRecord | None:
        versions = self._playbooks.get(pattern_key, [])
        return max(versions, key=lambda p: p.version) if versions else None

    def save_playbook(self, playbook: PlaybookRecord) -> None:
        if playbook.status == "active" and (not playbook.approved_by or playbook.approved_at is None):
            raise MemoryWriteBlocked("playbook ativo exige aprovação humana registrada")
        self._playbooks.setdefault(playbook.pattern_key, []).append(playbook)
        self.writes += 1

    def all_cases(self) -> list[CaseRecord]:
        return list(self._cases.values())


class ReadOnlyCaseMemoryRepository:
    """Envolve qualquer repositório e recusa escrita (SHADOW_READ_ONLY)."""

    def __init__(self, inner: CaseMemoryRepository) -> None:
        self._inner = inner

    def record_case(self, case: CaseRecord) -> tuple[CaseRecord, bool]:
        existing = self._inner.get_by_exact(case.exact_fingerprint)
        if existing is not None:
            return existing, False
        raise MemoryWriteBlocked("SHADOW_READ_ONLY: gravação de caso bloqueada")

    def get_by_exact(self, exact_fingerprint: str) -> CaseRecord | None:
        return self._inner.get_by_exact(exact_fingerprint)

    def list_by_pattern(self, pattern_key: str) -> list[CaseRecord]:
        return self._inner.list_by_pattern(pattern_key)

    def latest_by_lineage(self, lineage_key: str, before: datetime) -> CaseRecord | None:
        return self._inner.latest_by_lineage(lineage_key, before)

    def get_pattern_stats(self, pattern_key: str) -> PatternStatsRecord | None:
        return self._inner.get_pattern_stats(pattern_key)

    def save_pattern_stats(self, stats: PatternStatsRecord) -> None:
        raise MemoryWriteBlocked("SHADOW_READ_ONLY: gravação de estatística bloqueada")

    def get_current_playbook(self, pattern_key: str) -> PlaybookRecord | None:
        return self._inner.get_current_playbook(pattern_key)

    def save_playbook(self, playbook: PlaybookRecord) -> None:
        raise MemoryWriteBlocked("SHADOW_READ_ONLY: gravação de playbook bloqueada")
