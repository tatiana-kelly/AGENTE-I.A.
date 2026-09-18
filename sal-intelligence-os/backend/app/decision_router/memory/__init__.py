"""Memória persistente do Decision Router (Fase 3). Banco de produção: Postgres/Supabase — pendente D4."""

from app.decision_router.memory.recorder import MemoryMode, MemoryRecorder, RepositoryRouteStore
from app.decision_router.memory.records import CaseRecord, PatternStatsRecord, PlaybookRecord
from app.decision_router.memory.repository import (
    CaseMemoryRepository,
    InMemoryCaseMemoryRepository,
    MemoryWriteBlocked,
    ReadOnlyCaseMemoryRepository,
)

__all__ = [
    "CaseMemoryRepository",
    "CaseRecord",
    "InMemoryCaseMemoryRepository",
    "MemoryMode",
    "MemoryRecorder",
    "MemoryWriteBlocked",
    "PatternStatsRecord",
    "PlaybookRecord",
    "ReadOnlyCaseMemoryRepository",
    "RepositoryRouteStore",
]
