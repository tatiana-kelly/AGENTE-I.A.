"""Fingerprint determinístico fp/1 (JSON canônico + SHA-256, sem IA nem embeddings).

- exact: identifica o MESMO alerta (inclui período e padrão de concentração) → idempotência.
- pattern_key: identifica o MESMO padrão em outro período (troca período por granularidade).
- lineage_key: mesma métrica + entidade + granularidade → localiza caso anterior para calcular
  material_change (direção, faixa ou dimensão dominante podem ter mudado).
engine_source entra em exact e pattern_key: motores diferentes nunca são semelhantes.
"""

import hashlib
import json
from dataclasses import dataclass

from app.decision_router.bands import BandResult
from app.decision_router.contract import Fingerprints
from app.decision_router.inputs import AlertEnvelope, Direction
from app.decision_router.policy import MetricPolicy

FP_VERSION = "fp/1"
KNOWN_QUALITY_CLASSES = {"real", "partial", "mock"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_tagged(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def direction_of(envelope: AlertEnvelope) -> Direction:
    delta = envelope.alert.current_value - envelope.alert.reference_value
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _ranked_concentration(envelope: AlertEnvelope) -> list[dict]:
    items = [item for item in envelope.alert.concentration if isinstance(item, dict)]
    return sorted(items, key=lambda item: -float(item.get("share_pct") or 0))


def dominant_dimension(envelope: AlertEnvelope) -> str | None:
    ranked = _ranked_concentration(envelope)
    return str(ranked[0].get("dimension")) if ranked and ranked[0].get("dimension") is not None else None


def concentration_pattern(envelope: AlertEnvelope) -> list[str]:
    return [f"{item.get('dimension')}={item.get('value')}" for item in _ranked_concentration(envelope)[:3]]


def source_quality_class(envelope: AlertEnvelope) -> str:
    value = envelope.alert.source_quality.strip().lower()
    return value if value in KNOWN_QUALITY_CLASSES else "unknown"


@dataclass(frozen=True)
class FingerprintComponents:
    exact: dict
    similarity: dict
    lineage: dict


def fingerprint_components(
    envelope: AlertEnvelope, policy: MetricPolicy, band: BandResult, approval_flags: tuple[str, ...]
) -> FingerprintComponents:
    base = {
        "fp": FP_VERSION,
        "metric_id": envelope.alert.metric_id,
        "case_type": policy.case_type,
        "entity_type": envelope.entity_type,
        "entity_id": envelope.entity_id,
        "direction": direction_of(envelope),
        "magnitude_band": band.label,
        "engine_source": envelope.engine_source,
        "source_quality_class": source_quality_class(envelope),
        "approval_flags": sorted(approval_flags),
    }
    exact = {**base, "kind": "exact", "period": envelope.alert.period,
             "concentration_pattern": concentration_pattern(envelope)}
    similarity = {**base, "kind": "similarity", "granularity": policy.granularity,
                  "dominant_dimension": dominant_dimension(envelope)}
    lineage = {"fp": FP_VERSION, "kind": "lineage", "metric_id": envelope.alert.metric_id,
               "entity_type": envelope.entity_type, "entity_id": envelope.entity_id,
               "granularity": policy.granularity}
    return FingerprintComponents(exact=exact, similarity=similarity, lineage=lineage)


def compute_fingerprints(
    envelope: AlertEnvelope, policy: MetricPolicy, band: BandResult, approval_flags: tuple[str, ...]
) -> Fingerprints:
    components = fingerprint_components(envelope, policy, band, approval_flags)
    return Fingerprints(
        version=FP_VERSION,
        exact=sha256_tagged(components.exact),
        pattern_key=sha256_tagged(components.similarity),
        lineage_key=sha256_tagged(components.lineage),
    )
