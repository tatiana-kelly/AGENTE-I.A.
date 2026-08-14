"""Data Quality Gate — docs/ARCHITECTURE.md item 3.

Nenhum Alert pode nascer sem passar por esta validação primeiro
(docs/diagnostic-quality.md: "um alerta não é válido até passar por validação de
atualização, integridade, comparabilidade, fórmula, escopo, sazonalidade e materialidade").
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class QualityCheckResult:
    passed: bool
    score: int  # 0-100, comparável ao gate config/priority-scoring.yaml:minimum_data_quality
    reasons: list[str] = field(default_factory=list)


class DataQualityGate:
    """Cada check retorna (passou, motivo). O score final é a média ponderada dos checks que rodaram."""

    def __init__(self, minimum_score: int = 60) -> None:
        self.minimum_score = minimum_score

    def check_freshness(self, last_updated_at: datetime, max_age: timedelta) -> tuple[bool, str]:
        age = datetime.now(UTC) - last_updated_at
        if age > max_age:
            return False, f"dado desatualizado: última atualização há {age}, limite é {max_age}"
        return True, "atualização dentro do limite"

    def check_completeness(self, record: dict, required_fields: list[str]) -> tuple[bool, str]:
        missing = [f for f in required_fields if record.get(f) in (None, "", [])]
        if missing:
            return False, f"campos obrigatórios ausentes: {', '.join(missing)}"
        return True, "completo"

    def check_duplicity(self, dedup_key: str, seen_keys: set[str]) -> tuple[bool, str]:
        if dedup_key in seen_keys:
            return False, f"chave de deduplicação já vista: {dedup_key}"
        return True, "sem duplicidade"

    def check_comparability(self, current_grain: str, reference_grain: str) -> tuple[bool, str]:
        if current_grain != reference_grain:
            return False, f"granularidade incomparável: atual={current_grain}, referência={reference_grain}"
        return True, "granularidade comparável"

    def check_materiality(self, absolute_delta: float, materiality_threshold: float) -> tuple[bool, str]:
        if abs(absolute_delta) < materiality_threshold:
            return False, f"desvio abaixo do limite de materialidade ({materiality_threshold})"
        return True, "material"

    def evaluate(self, checks: list[tuple[bool, str]]) -> QualityCheckResult:
        if not checks:
            return QualityCheckResult(passed=False, score=0, reasons=["nenhum check executado"])
        passed_count = sum(1 for ok, _ in checks if ok)
        score = round(100 * passed_count / len(checks))
        reasons = [reason for ok, reason in checks if not ok]
        return QualityCheckResult(passed=score >= self.minimum_score and not reasons, score=score, reasons=reasons)
