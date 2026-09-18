"""Projeção faturamento × custos por base (FASE C/D da Torre) → alertas executivos.

Fonte (somente leitura): data/projecao_fatxcustos_latest.json, gerado por snapshot/orquestrador_projecao.py.
Cada item de alertas_executivos é um alerta do motor; os números vêm do item correspondente em `bases`.
case_type desta métrica é UNKNOWN na política (B4.4) — o Router não escolhe especialista.
"""

from app.decision_router.adapters.base import (
    PRIORITY_SEVERITY,
    AdaptedAlert,
    AdapterOutput,
    SkippedRecord,
    TorreDataReader,
    missing_file_output,
    parse_torre_timestamp,
)
from app.decision_router.inputs import AlertEnvelope
from app.schemas.alert import AlertBase

SOURCE = "torre.orquestrador_projecao"
FILE = "projecao_fatxcustos_latest.json"
METRIC_ID = "projecao-faturamento-custos-base"


class ProjectionAlertAdapter:
    name = SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return missing_file_output(SOURCE, FILE)
        document = reader.read_json(FILE)
        generated_at = parse_torre_timestamp(document["gerado_em"])
        report_date = str(document.get("report_date") or document["gerado_em"][:10])
        bases = {item.get("base"): item for item in document.get("bases") or []}
        items = document.get("alertas_executivos") or []
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for item in items:
            code = item.get("base")
            base = bases.get(code)
            if base is None or base.get("aceleracao_pct") is None:
                skipped.append(SkippedRecord(SOURCE, str(code), "alerta sem base correspondente ou sem aceleracao_pct"))
                continue
            priority = item.get("prioridade")
            severity = PRIORITY_SEVERITY.get(priority, "medium")
            alert = AlertBase(
                metric_id=METRIC_ID,
                title=f"Projeção de capacidade {code}: {base.get('classificacao')}",
                period=report_date,
                current_value=float(base["aceleracao_pct"]),
                reference_value=0.0,
                materiality=0.0,
                severity=severity,
                source_quality="real",
                concentration=[{"dimension": "base", "value": code, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="base", entity_id=str(code),
                evaluated_at=generated_at, rules_version=rules_version,
            )
            orchestrator = base.get("orquestrador") or {}
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{code}:{report_date}",
                source=SOURCE,
                envelope=envelope,
                source_ref=f"{FILE} alertas_executivos[base={code}] + bases[base={code}]",
                transformations=(
                    "current_value = bases.aceleracao_pct; reference_value = 0 (aceleração nula)",
                    "materiality = 0: o motor não grava impacto absoluto em R$ para a projeção",
                    "period = report_date do motor",
                    "severity pelo ordinal da prioridade do motor"
                    if priority in PRIORITY_SEVERITY else "prioridade fora de P0–P3: severity 'medium' neutro",
                ),
                notes=(
                    (
                        f"motor: prioridade={priority} score={item.get('score')} "
                        f"decisao_recomendada={orchestrator.get('decisao_recomendada')}"
                    ),
                ),
            ))
        return AdapterOutput(SOURCE, FILE, len(items), tuple(alerts), tuple(skipped))
