"""Custo por CT-e e custo × performance por base (módulo B do painel da Torre).

Fonte (somente leitura): data/latest.json → diagnosticos_operacionais.custo_performance, gerado por
snapshot/motor_snapshot_painel.py (dataset BI Custo Entrega + BI Performance).
- custo-por-cte-base: só bases com acima_alerta_cte = true (flag do próprio motor).
- custo-performance-base: só categorias diferentes de OK. A categoria depende do KPI de performance;
  quando o motor grava kpi_performance = 0, o KPI não veio e a categoria não é confiável → insufficient.
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
from app.decision_router.inputs import AlertEnvelope, EngineSignals
from app.schemas.alert import AlertBase

SOURCE = "torre.motor_snapshot_painel"
FILE = "latest.json"
CTE_METRIC = "custo-por-cte-base"
PERF_METRIC = "custo-performance-base"
COVERAGE_SCOPE = "custo_performance"


def _coverage_pct(rows: list[dict]) -> float | None:
    """Mesma regra de motor_snapshot_painel.py:2186 — base com custo > 0 e qtd_ctes > 0."""
    if not rows:
        return None
    ok = sum(1 for row in rows if (row.get("custo") or 0) > 0 and (row.get("qtd_ctes") or 0) > 0)
    return round(100 * ok / len(rows), 2)


def _period(document: dict) -> str:
    period = document.get("periodo")
    if isinstance(period, dict) and period.get("fim"):
        return str(period["fim"])[:7]
    return str(document.get("gerado_em", ""))[:7]


def _block(document: dict) -> dict:
    return (document.get("diagnosticos_operacionais") or {}).get("custo_performance") or {}


class CostPerCteAdapter:
    name = f"{SOURCE}:{CTE_METRIC}"

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return missing_file_output(self.name, FILE)
        document = reader.read_json(FILE)
        block = _block(document)
        rows = block.get("dados") or []
        generated_at = parse_torre_timestamp(document["gerado_em"])
        period = _period(document)
        coverage = _coverage_pct(rows)
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for row in rows:
            base = row.get("sigla")
            if not row.get("acima_alerta_cte"):
                skipped.append(SkippedRecord(self.name, str(base), "acima_alerta_cte = false"))
                continue
            if row.get("custo_cte") is None or row.get("alerta_cte_ref") is None:
                skipped.append(SkippedRecord(self.name, str(base), "sem custo_cte ou alerta_cte_ref"))
                continue
            alert = AlertBase(
                metric_id=CTE_METRIC,
                title=f"Custo por CT-e {base} acima da referência de alerta",
                period=period,
                current_value=float(row["custo_cte"]),
                reference_value=float(row["alerta_cte_ref"]),
                materiality=0.0,
                severity="medium",
                source_quality="real",
                concentration=[{"dimension": "base", "value": base, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="base", entity_id=str(base),
                evaluated_at=generated_at, rules_version=rules_version,
                signals=EngineSignals(coverage_scope=COVERAGE_SCOPE, coverage_pct=coverage),
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{CTE_METRIC}:{base}:{period}",
                source=self.name,
                envelope=envelope,
                source_ref=f"{FILE} diagnosticos_operacionais.custo_performance.dados[sigla={base}]",
                transformations=(
                    "current_value = custo_cte; reference_value = alerta_cte_ref (referência de alerta do motor)",
                    "materiality = 0: o motor não grava impacto absoluto do excesso",
                    "period = mês de periodo.fim (custo acumulado do mês)",
                    "coverage_pct = regra campos_ok do motor (custo > 0 e qtd_ctes > 0)",
                    SEVERITY_NOT_PROVIDED,
                ),
                notes=(f"kpi_performance={row.get('kpi_performance')} categoria={row.get('categoria')}",),
            ))
        notes = (f"status do módulo no motor: {block.get('status')} (n={block.get('n')})",
                 f"cobertura calculada pela regra do motor: {coverage}%")
        return AdapterOutput(self.name, FILE, len(rows), tuple(alerts), tuple(skipped), notes)


class CostPerformanceAdapter:
    name = f"{SOURCE}:{PERF_METRIC}"

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return missing_file_output(self.name, FILE)
        document = reader.read_json(FILE)
        block = _block(document)
        rows = block.get("dados") or []
        generated_at = parse_torre_timestamp(document["gerado_em"])
        period = _period(document)
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for row in rows:
            base = row.get("sigla")
            category = row.get("categoria")
            if category in (None, "OK"):
                skipped.append(SkippedRecord(self.name, str(base), f"categoria do motor = {category}"))
                continue
            kpi_missing = not row.get("kpi_performance")
            transformations = [
                "current_value = delta_custo_pct; reference_value = 0 (variação contra o mês anterior)",
                "materiality = 0: o motor não grava impacto absoluto da categoria",
                "signals.category = categoria do motor (A/B/C/D)",
                SEVERITY_NOT_PROVIDED,
            ]
            if kpi_missing:
                transformations.append("kpi_performance = 0 (KPI ausente) → categoria não confiável → insufficient")
            alert = AlertBase(
                metric_id=PERF_METRIC,
                title=f"Custo × performance {base}: categoria {category} ({row.get('hipotese')})",
                period=period,
                current_value=float(row.get("delta_custo_pct") or 0.0),
                reference_value=0.0,
                materiality=0.0,
                severity="medium",
                source_quality="insufficient" if kpi_missing else "real",
                concentration=[{"dimension": "base", "value": base, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="base", entity_id=str(base),
                evaluated_at=generated_at, rules_version=rules_version,
                signals=EngineSignals(category=category),
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{PERF_METRIC}:{base}:{period}",
                source=self.name,
                envelope=envelope,
                source_ref=f"{FILE} diagnosticos_operacionais.custo_performance.dados[sigla={base}]",
                transformations=tuple(transformations),
                notes=(f"kpi_performance={row.get('kpi_performance')} delta_perf_pp={row.get('delta_perf_pp')}",),
            ))
        kpi_present = sum(1 for row in rows if row.get("kpi_performance"))
        notes = (f"bases com KPI de performance: {kpi_present}/{len(rows)}",)
        return AdapterOutput(self.name, FILE, len(rows), tuple(alerts), tuple(skipped), notes)
