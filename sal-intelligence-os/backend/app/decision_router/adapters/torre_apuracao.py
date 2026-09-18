"""Conferência do card de apuração × Torre e reconciliação Torre × apuração.

Fontes (somente leitura):
- data/apuracao_alertas_enviados.json — registro de snapshot/conferir_apuracao_custo.py: um alerta por data
  de apuração com delta_total e motivo (enviado ou suprimido).
- data/reconciliacao_torre_apuracao.json — linhas por categoria com classificacao do próprio motor.
"""

from app.decision_router.adapters.base import (
    SEVERITY_NOT_PROVIDED,
    AdaptedAlert,
    AdapterOutput,
    SkippedRecord,
    TorreDataReader,
    missing_file_output,
    parse_torre_timestamp,
)
from app.decision_router.inputs import AlertEnvelope, QualityInputs
from app.schemas.alert import AlertBase

CARD_SOURCE = "torre.conferir_apuracao_custo"
CARD_FILE = "apuracao_alertas_enviados.json"
CARD_METRIC = "divergencia-card-apuracao-ssw"

RECON_SOURCE = "torre.reconciliacao_torre_apuracao"
RECON_FILE = "reconciliacao_torre_apuracao.json"
RECON_METRIC = "reconciliacao-torre-apuracao"  # sem correspondência na política do Router


class ApuracaoCardDivergenceAdapter:
    name = CARD_SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(CARD_FILE):
            return missing_file_output(CARD_SOURCE, CARD_FILE)
        registry = reader.read_json(CARD_FILE).get("alertas") or {}
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for apuracao_date, record in sorted(registry.items()):
            if record.get("delta_total") is None or not record.get("em"):
                skipped.append(SkippedRecord(CARD_SOURCE, apuracao_date, "registro sem delta_total ou horário"))
                continue
            delta = float(record["delta_total"])
            alert = AlertBase(
                metric_id=CARD_METRIC,
                title=f"Divergência card de apuração × Torre em {apuracao_date}",
                period=apuracao_date,
                current_value=delta,
                reference_value=0.0,
                materiality=abs(delta),
                severity="medium",
                source_quality="real",
                concentration=[],  # o registro não diz onde está a diferença
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=CARD_SOURCE, entity_type="apuracao_total", entity_id="SAL",
                evaluated_at=parse_torre_timestamp(record["em"]), rules_version=rules_version,
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{CARD_SOURCE}:{apuracao_date}",
                source=CARD_SOURCE,
                envelope=envelope,
                source_ref=f"{CARD_FILE} alertas[{apuracao_date}]",
                transformations=(
                    "current_value = delta_total; reference_value = 0 (diferença esperada nula)",
                    "materiality = |delta_total| (R$)",
                    "concentration vazia: o registro não identifica a categoria da diferença",
                    SEVERITY_NOT_PROVIDED,
                ),
                notes=(f"motivo registrado pelo motor: {record.get('motivo')}",),
            ))
        return AdapterOutput(CARD_SOURCE, CARD_FILE, len(registry), tuple(alerts), tuple(skipped))


class ReconciliationTorreApuracaoAdapter:
    name = RECON_SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(RECON_FILE):
            return missing_file_output(RECON_SOURCE, RECON_FILE)
        document = reader.read_json(RECON_FILE)
        generated_at = parse_torre_timestamp(document["gerado_em"])
        torre, apuracao = document.get("periodo_torre") or {}, document.get("periodo_apuracao") or {}
        torre_period = f"{torre.get('inicio')}..{torre.get('fim')}"
        apuracao_period = f"{apuracao.get('inicio')}..{apuracao.get('fim')}"
        lines = document.get("linhas") or []
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for line in lines:
            category = line.get("categoria")
            if line.get("classificacao") != "INVESTIGAR":
                skipped.append(SkippedRecord(RECON_SOURCE, str(category),
                                             f"classificacao do motor = {line.get('classificacao')}"))
                continue
            if line.get("torre") is None or line.get("apuracao") is None or line.get("delta") is None:
                skipped.append(SkippedRecord(RECON_SOURCE, str(category), "linha sem torre, apuracao ou delta"))
                continue
            alert = AlertBase(
                metric_id=RECON_METRIC,
                title=f"Reconciliação Torre × apuração: {category}",
                period=torre_period,
                current_value=float(line["torre"]),
                reference_value=float(line["apuracao"]),
                materiality=abs(float(line["delta"])),
                severity="medium",
                source_quality="real",
                concentration=[{"dimension": "categoria", "value": category, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=RECON_SOURCE, entity_type="categoria", entity_id=str(category),
                evaluated_at=generated_at, rules_version=rules_version,
                quality_inputs=QualityInputs(current_grain=torre_period, reference_grain=apuracao_period),
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{RECON_SOURCE}:{category}:{torre_period}",
                source=RECON_SOURCE,
                envelope=envelope,
                source_ref=f"{RECON_FILE} linhas[categoria={category}]",
                transformations=(
                    "current_value = torre; reference_value = apuracao; materiality = |delta|",
                    "comparabilidade: período da Torre × período da apuração (DataQualityGate)",
                    SEVERITY_NOT_PROVIDED,
                ),
                notes=(f"causa registrada pelo motor: {line.get('causa')}",
                       f"mesmo_periodo={document.get('mesmo_periodo')}"),
            ))
        return AdapterOutput(RECON_SOURCE, RECON_FILE, len(lines), tuple(alerts), tuple(skipped))
