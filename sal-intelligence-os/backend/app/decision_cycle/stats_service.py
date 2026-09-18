"""Ligação do ciclo com pattern_stats (Fase 3). Escreve SOMENTE em modo persistente explícito.

Em SHADOW_READ_ONLY o serviço calcula o que seria gravado e devolve o registro projetado, sem tocar no
repositório. Playbook nunca é criado aqui, e approved_decisions/verified_* só mudam com decisão e verificação
reais — nunca por contagem de ocorrências.
"""

from dataclasses import dataclass
from datetime import datetime

from app.decision_cycle.learning import LearningRecord
from app.decision_cycle.verification import VerificationVerdict
from app.decision_router.memory.recorder import MemoryMode
from app.decision_router.memory.records import PatternStatsRecord
from app.decision_router.memory.repository import CaseMemoryRepository, MemoryWriteBlocked
from app.schemas.enums import DecisionOutcome


@dataclass
class PatternStatsService:
    repository: CaseMemoryRepository
    mode: MemoryMode = MemoryMode.SHADOW_READ_ONLY
    persist_enabled: bool = False

    def __post_init__(self) -> None:
        if self.mode is MemoryMode.PERSIST and not self.persist_enabled:
            raise MemoryWriteBlocked("PERSIST exige habilitação explícita (persist_enabled=True)")

    @property
    def writes(self) -> bool:
        return self.mode is not MemoryMode.SHADOW_READ_ONLY

    def project(self, learning: LearningRecord, now: datetime, *, reused: bool = False,
                agent_calls: int = 0, useful_agent_calls: int = 0) -> PatternStatsRecord:
        """Estatística que o ciclo produziria — pura, sem efeito."""
        base = self.repository.get_pattern_stats(learning.pattern_key) or PatternStatsRecord(
            pattern_key=learning.pattern_key)
        approved = 1 if learning.decision_outcome is DecisionOutcome.APPROVED else 0
        ok = 1 if learning.verified_result is VerificationVerdict.VERIFIED_OK else 0
        fail = 1 if learning.verified_result is VerificationVerdict.VERIFIED_FAIL else 0
        return base.model_copy(update={
            "approved_decisions": base.approved_decisions + approved,
            "reuse_count": base.reuse_count + (1 if reused else 0),
            "reuse_verified_fail": base.reuse_verified_fail + (1 if reused and fail else 0),
            "verified_ok": base.verified_ok + ok,
            "verified_fail": base.verified_fail + fail,
            "agent_calls": base.agent_calls + agent_calls,
            "useful_agent_calls": base.useful_agent_calls + useful_agent_calls,
            "updated_at": now,
        })

    def apply(self, learning: LearningRecord, now: datetime, **kwargs) -> PatternStatsRecord:
        """Grava a projeção — recusado em SHADOW_READ_ONLY."""
        projected = self.project(learning, now, **kwargs)
        if not self.writes:
            raise MemoryWriteBlocked("SHADOW_READ_ONLY: estatísticas não são atualizadas automaticamente")
        self.repository.save_pattern_stats(projected)
        return projected
