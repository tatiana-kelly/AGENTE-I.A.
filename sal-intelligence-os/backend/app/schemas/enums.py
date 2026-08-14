from enum import StrEnum


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionStatus(StrEnum):
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"
    READY_FOR_DECISION = "READY_FOR_DECISION"
    CONTAINMENT_ONLY = "CONTAINMENT_ONLY"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"


class HypothesisStatus(StrEnum):
    UNTESTED = "untested"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class RecommendationType(StrEnum):
    CONTAINMENT = "containment"
    STRUCTURAL = "structural"
    OPTIMIZATION = "optimization"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Reversibility(StrEnum):
    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"


class DecisionOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
