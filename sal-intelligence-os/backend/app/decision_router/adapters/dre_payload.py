"""Adaptador DRE → Decision Router: realizado × orçado por linha (escopo aprovado pela Tatiana em 2026-09-19).

Lê SOMENTE o payload publicado do DRE (`app/web/public/payload.json` no repositório do DRE). Regras:
- só linhas ANALÍTICAS (grupos e totalizadores repetiriam o mesmo desvio);
- impacto no EBITDA = sinal_ebitda × (REALIZADO − ORCADO) — a mesma fórmula da tela "Análise de desvios" do DRE,
  com o orçado como base (escopo aprovado); impacto < 0 = desfavorável;
- Pareto: entram as linhas desfavoráveis que, em ordem de impacto, somam até 70% do desvio desfavorável total
  (a regra de fila de 70% do próprio DRE) — a linha que cruza os 70% entra;
- FORA sempre: linhas restritas (linha_id ≥ 200) e folha/pró-labore/lucros (salário, 13º, férias, rescisão, FGTS,
  INSS, participação/distribuição de lucros) — decisão da Tatiana; nenhum lançamento, fornecedor ou histórico.
"""

import re
from datetime import datetime

from app.decision_router.adapters.base import AdaptedAlert, AdapterOutput, SkippedRecord, TorreDataReader
from app.decision_router.inputs import AlertEnvelope, EngineSignals
from app.schemas.alert import AlertBase

SOURCE = "dre.payload_realizado_vs_orcado"
FILE = "payload.json"
METRIC_ID = "dre-linha-realizado-vs-orcado"
PARETO_SHARE = 0.70
RESTRICTED_FROM_ID = 200
SENSITIVE = re.compile(r"sal[aá]rio|13[ºo°]|folha|pr[oó]-?\s?labore|lucros|f[eé]rias|rescis|fgts|\binss\b", re.IGNORECASE)


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class DrePayloadAdapter:
    name = SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return AdapterOutput(SOURCE, None, 0, (), notes=(f"arquivo não encontrado: {FILE}",))
        document = reader.read_json(FILE)
        competencia = str(document.get("competencia") or "")
        generated_at = datetime.fromisoformat(str(document["gerado_em"]))
        status = str(document.get("status") or "")
        rows = document.get("matriz") or []
        skipped: list[SkippedRecord] = []
        unfavorable: list[tuple[float, dict, float, float]] = []
        for row in rows:
            ref = f"matriz[linha_id={row.get('linha_id')}]"
            if row.get("nivel") != "ANALITICA":
                continue
            if int(row.get("linha_id") or 0) >= RESTRICTED_FROM_ID or SENSITIVE.search(str(row.get("rotulo") or "")):
                skipped.append(SkippedRecord(SOURCE, ref, "linha restrita ou de folha/pró-labore/lucros: fora do escopo"))
                continue
            realized, budget, sign = _num(row.get("REALIZADO")), _num(row.get("ORCADO")), row.get("sinal_ebitda")
            if realized is None or budget is None or sign not in (1, -1):
                continue
            impact = sign * (realized - budget)
            if impact < 0:
                unfavorable.append((impact, row, realized, budget))

        unfavorable.sort(key=lambda item: item[0])  # mais negativo primeiro
        total = sum(-impact for impact, *_ in unfavorable)
        alerts: list[AdaptedAlert] = []
        cumulative = 0.0
        for impact, row, realized, budget in unfavorable:
            if total <= 0 or cumulative >= PARETO_SHARE * total:
                break
            cumulative += -impact
            line_id = str(row["linha_id"])
            alert = AlertBase(
                metric_id=METRIC_ID,
                title=f"DRE {competencia}: {row.get('rotulo')} desfavorável ao orçado",
                period=competencia,
                current_value=realized,
                reference_value=budget,
                materiality=-impact,
                severity="medium",
                source_quality="real",
                concentration=[{"dimension": "linha_dre", "value": line_id, "share_pct": round(100 * -impact / total, 2)}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="linha_dre", entity_id=line_id, evaluated_at=generated_at,
                rules_version=rules_version, signals=EngineSignals(single_day=False, category="DESFAVORAVEL_PARETO_70"),
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{competencia}:{line_id}",
                source=SOURCE,
                envelope=envelope,
                source_ref=f"{FILE} matriz[linha_id={line_id}]",
                transformations=(
                    "current_value = REALIZADO; reference_value = ORCADO (base aprovada: orçado)",
                    "materiality = |sinal_ebitda × (REALIZADO − ORCADO)| em R$ (impacto desfavorável no EBITDA)",
                    f"Pareto: linhas desfavoráveis até {int(PARETO_SHARE * 100)}% do desvio desfavorável total",
                    f"competência com status {status} no payload publicado",
                ),
            ))
        notes = (f"linhas desfavoráveis={len(unfavorable)}; no Pareto={len(alerts)}; status={status}",)
        return AdapterOutput(SOURCE, FILE, len(rows), tuple(alerts), tuple(skipped), notes)
