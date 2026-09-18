"""Divergência de custo por rota SSW oficial × BI e memória do registro de aprendizado da Torre.

Fontes (somente leitura):
- data/divergencia_rota_ssw_bi.json — gerado por snapshot/divergencia_rota_ssw_bi.py;
  cada item de rotas_divergentes já passou pelos limiares do motor (min_abs e min_pct).
- data/aprendizado_agentes.json — gerado por snapshot/aprendizado_diario_agentes.py
  (estado_atual por rota + falsos_positivos).
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
from app.decision_router.contract import MISSING_BAND
from app.decision_router.inputs import AlertEnvelope, MemoryEntry
from app.schemas.alert import AlertBase

SOURCE = "torre.divergencia_rota_ssw_bi"
FILE = "divergencia_rota_ssw_bi.json"
LEDGER_FILE = "aprendizado_agentes.json"
METRIC_ID = "divergencia-custo-rota-ssw-bi"


class SswBiRouteDivergenceAdapter:
    name = SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return missing_file_output(SOURCE, FILE)
        document = reader.read_json(FILE)
        generated_at = parse_torre_timestamp(document["gerado_em"])
        run_day = document["gerado_em"][:10]
        items = document.get("rotas_divergentes") or []
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for item in items:
            route = item.get("rota")
            oficial, bi = item.get("oficial_ssw"), item.get("bi")
            if not route or oficial is None or bi is None or item.get("delta") is None:
                skipped.append(SkippedRecord(SOURCE, str(route), "rota sem oficial_ssw, bi ou delta"))
                continue
            alert = AlertBase(
                metric_id=METRIC_ID,
                title=f"Custo por rota SSW×BI {route} ({item.get('sentido')})",
                period=run_day,
                current_value=float(oficial),
                reference_value=float(bi),
                materiality=abs(float(item["delta"])),
                severity="medium",
                source_quality="real",
                concentration=[{"dimension": "rota", "value": route, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="rota", entity_id=route,
                evaluated_at=generated_at, rules_version=rules_version,
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{route}:{run_day}",
                source=SOURCE,
                envelope=envelope,
                source_ref=f"{FILE} rotas_divergentes[rota={route}]",
                transformations=(
                    "current_value = oficial_ssw; reference_value = bi (delta do motor = oficial − bi)",
                    "materiality = |delta| do motor (R$)",
                    "period = data de geração do arquivo (rodada diária)",
                    "concentration = a própria rota (100%): o motor agrega por rota",
                    SEVERITY_NOT_PROVIDED,
                ),
            ))
        limiares = document.get("limiares", {})
        notes = (
            f"limiares do motor: min_abs={limiares.get('min_abs')} min_pct={limiares.get('min_pct')}",
            f"escopo do motor: {document.get('escopo')} (afeta_macro={document.get('resumo', {}).get('afeta_macro')})",
        )
        return AdapterOutput(SOURCE, FILE, len(items), tuple(alerts), tuple(skipped), notes)


def ledger_memory_entries(reader: TorreDataReader) -> tuple[dict[str, MemoryEntry], tuple[str, ...]]:
    """Memória por rota a partir do registro de aprendizado real. Chave = nome da rota."""
    if not reader.exists(LEDGER_FILE):
        return {}, (f"arquivo não encontrado: {LEDGER_FILE}",)
    ledger = reader.read_json(LEDGER_FILE)
    false_positives = ledger.get("falsos_positivos") or {}
    entries: dict[str, MemoryEntry] = {}
    for route, state in (ledger.get("estado_atual") or {}).items():
        delta = state.get("delta")
        direction = "flat" if not delta else ("up" if delta > 0 else "down")
        fp = false_positives.get(route)
        entries[route] = MemoryEntry(
            engine_source=SOURCE,
            direction=direction,
            delta=delta,
            magnitude_band=MISSING_BAND,
            status=state.get("status", "ABERTA"),
            causa=state.get("causa"),
            false_positive_active=fp is not None,
            false_positive_reason=(fp or {}).get("motivo"),
            source_ref=f"{LEDGER_FILE} estado_atual[{route}]",
        )
    with_cause = sum(1 for entry in entries.values() if entry.causa)
    notes = (
        (
            f"registro de aprendizado: {len(entries)} rotas, {with_cause} com causa registrada, "
            f"{len(false_positives)} falsos positivos"
        ),
    )
    return entries, notes
