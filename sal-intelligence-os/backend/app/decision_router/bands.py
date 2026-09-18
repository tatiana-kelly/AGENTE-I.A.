"""Faixa de magnitude do fingerprint fp/1 — somente limites existentes; sem limite, MISSING."""

from dataclasses import dataclass

from app.decision_router.contract import MISSING_BAND
from app.decision_router.inputs import AlertEnvelope
from app.decision_router.policy import MetricPolicy


@dataclass(frozen=True)
class BandResult:
    label: str
    ordered_labels: tuple[str, ...] | None
    rule_ref: str | None

    @property
    def missing(self) -> bool:
        return self.label == MISSING_BAND

    def adjacent_to(self, other_label: str) -> bool:
        if self.ordered_labels is None or self.missing or other_label not in self.ordered_labels:
            return False
        return abs(self.ordered_labels.index(self.label) - self.ordered_labels.index(other_label)) == 1


_MISSING = BandResult(MISSING_BAND, None, None)


def classify_band(policy: MetricPolicy, envelope: AlertEnvelope) -> BandResult:
    value = envelope.alert.current_value
    if policy.band_kind == "metric_definition":
        thresholds = policy.thresholds
        if thresholds is None or thresholds.source == "mock":
            return _MISSING
        order = ("META", "ATENCAO", "AVISO", "CRITICO")
        # B6.5 (pendente): valor igual ao limite pertence à faixa pior.
        if value >= thresholds.target:
            label = "META"
        elif value > thresholds.warning:
            label = "ATENCAO"
        elif value > thresholds.critical:
            label = "AVISO"
        else:
            label = "CRITICO"
        return BandResult(label, order, thresholds.rule_ref)
    if policy.band_kind == "engine_classes":
        classes = policy.engine_classes.get(envelope.engine_source)
        if not classes:
            return _MISSING
        order = tuple(item.label for item in classes)
        for item in classes:
            if value >= item.lower and (item.upper is None or value < item.upper):
                return BandResult(item.label, order, policy.engine_classes_ref.get(envelope.engine_source))
        return _MISSING
    if policy.band_kind == "reference_threshold":
        reference = policy.reference_by_entity.get(envelope.entity_id, policy.reference_default)
        if reference is None:
            return _MISSING
        label = "ACIMA_REFERENCIA" if value > reference else "DENTRO_REFERENCIA"
        return BandResult(label, ("DENTRO_REFERENCIA", "ACIMA_REFERENCIA"), policy.reference_ref)
    if policy.band_kind == "engine_category":
        category = envelope.signals.category
        if not category:
            return _MISSING
        return BandResult(category, None, policy.mapping_ref)
    return _MISSING


def classify_value(policy: MetricPolicy, envelope: AlertEnvelope, value: float) -> BandResult:
    """Classifica outro valor com as mesmas regras (ex.: o dia isolado frente à janela)."""
    alert = envelope.alert.model_copy(update={"current_value": value})
    return classify_band(policy, envelope.model_copy(update={"alert": alert}))
