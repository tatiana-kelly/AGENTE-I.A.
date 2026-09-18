"""Playbooks: candidato × aprovado. O Router nunca ativa um playbook.

candidate_playbook() sempre nasce 'pending_approval'. approve_playbook() é a única porta para 'active' e exige:
aprovação humana com papel de decisão, evidência, histórico suficiente, verificação positiva e regra compatível.
As mesmas condições existem como constraint na tabela decision_router.playbooks (Fase 3).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.decision_cycle.governance import Actor, GovernanceViolation, require_approval_role
from app.decision_router.memory.records import PatternStatsRecord, PlaybookRecord

MIN_OCCURRENCES = 3
MIN_APPROVED_DECISIONS = 1
MIN_VERIFIED_OK = 1


@dataclass(frozen=True)
class PlaybookEligibility:
    eligible: bool
    failures: tuple[str, ...]


def candidate_playbook(*, pattern_key: str, case_type: str, name: str, conditions: dict,
                       recommended_action: dict, rules_version: str, magnitude_band: str,
                       stats: PatternStatsRecord | None, now: datetime, version: int = 1) -> PlaybookRecord:
    """Recorrência cria CANDIDATO, nunca playbook ativo."""
    return PlaybookRecord(
        id=str(uuid.uuid4()), pattern_key=pattern_key, case_type=case_type, name=name, version=version,
        conditions=conditions, recommended_action=recommended_action, rules_version=rules_version,
        magnitude_band=magnitude_band, status="pending_approval",
        approved_count=stats.approved_decisions if stats else 0,
        verified_ok_count=stats.verified_ok if stats else 0,
        verified_fail_count=stats.verified_fail if stats else 0,
        created_at=now, updated_at=now,
    )


def eligibility(playbook: PlaybookRecord, stats: PatternStatsRecord | None, evidence: tuple[str, ...],
                current_rules_version: str) -> PlaybookEligibility:
    failures: list[str] = []
    if not evidence:
        failures.append("sem evidência anexada")
    if stats is None or stats.occurrences < MIN_OCCURRENCES:
        failures.append(f"histórico insuficiente ({stats.occurrences if stats else 0} < {MIN_OCCURRENCES})")
    if stats is None or stats.approved_decisions < MIN_APPROVED_DECISIONS:
        failures.append("sem decisão aprovada no padrão")
    if stats is None or stats.verified_ok < MIN_VERIFIED_OK:
        failures.append("sem verificação positiva")
    if stats is not None and stats.verified_fail > 0:
        failures.append(f"há {stats.verified_fail} verificações com falha")
    if playbook.rules_version != current_rules_version:
        failures.append("rules_version incompatível")
    return PlaybookEligibility(not failures, tuple(failures))


def approve_playbook(playbook: PlaybookRecord, actor: Actor, *, stats: PatternStatsRecord | None,
                     evidence: tuple[str, ...], current_rules_version: str, now: datetime) -> PlaybookRecord:
    require_approval_role(actor, f"ativação do playbook {playbook.id}")
    verdict = eligibility(playbook, stats, evidence, current_rules_version)
    if not verdict.eligible:
        raise GovernanceViolation("playbook não elegível: " + "; ".join(verdict.failures))
    return playbook.model_copy(update={"status": "active", "approved_by": actor.id, "approved_at": now,
                                       "valid_from": now, "updated_at": now})
