"""Clientes deficitários (agendamentos dedicados com custo > faturamento recorrente).

Fonte (somente leitura): data/clientes_deficitarios.json, gerado por snapshot/clientes_deficitarios.py.
Só a lista `deficitarios` (casos que já passaram pelos pisos do motor) vira alerta; `quase_la` não é alerta.
Nomes de clientes são pseudonimizados no envelope (dado comercial) — o original fica só na fonte.
"""

from app.decision_router.adapters.base import (
    SEVERITY_NOT_PROVIDED,
    AdaptedAlert,
    AdapterOutput,
    SkippedRecord,
    TorreDataReader,
    missing_file_output,
    parse_torre_timestamp,
    pseudonymize,
)
from app.decision_router.inputs import AlertEnvelope
from app.schemas.alert import AlertBase

SOURCE = "torre.clientes_deficitarios"
FILE = "clientes_deficitarios.json"
METRIC_ID = "clientes-deficitarios"


class DeficitClientsAdapter:
    name = SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        if not reader.exists(FILE):
            return missing_file_output(SOURCE, FILE)
        document = reader.read_json(FILE)
        meta = document.get("meta") or {}
        generated_at = parse_torre_timestamp(meta["gerado_em"])
        window = meta.get("janela_real") or {}
        period = f"{window.get('de')}..{window.get('ate')}"
        minimum = meta.get("min_recorrencia")
        items = document.get("deficitarios") or []
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for index, item in enumerate(items):
            payer = item.get("cliente_pagador")
            client = payer if payer and payer != "ND" else item.get("cliente_destinatario")
            recurrence = item.get("agendamentos")
            loss = item.get("prejuizo_periodo_rs")
            if not client or recurrence is None or loss is None or minimum is None:
                skipped.append(SkippedRecord(SOURCE, f"deficitarios[{index}]", "sem cliente, agendamentos, prejuízo ou piso"))
                continue
            entity = pseudonymize(client)
            alert = AlertBase(
                metric_id=METRIC_ID,
                title=f"Agendamentos com custo > faturamento ({item.get('modal')}) cliente {entity}",
                period=period,
                current_value=float(recurrence),
                reference_value=float(minimum),
                materiality=abs(float(loss)),
                severity="medium",
                source_quality="real",
                concentration=[{"dimension": "cliente", "value": entity, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="cliente", entity_id=entity,
                evaluated_at=generated_at, rules_version=rules_version,
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{entity}:{period}",
                source=SOURCE,
                envelope=envelope,
                source_ref=f"{FILE} deficitarios[{index}]",
                transformations=(
                    "current_value = agendamentos (recorrência); reference_value = meta.min_recorrencia",
                    "materiality = prejuizo_periodo_rs do motor",
                    "cliente pseudonimizado (sha256): pagador, ou destinatário quando pagador = ND",
                    SEVERITY_NOT_PROVIDED,
                ),
            ))
        notes = (
            f"janela pedida {meta.get('janela_pedida_dias')} dias, real {window.get('dias')} dias",
            f"deficitarios={len(items)} quase_la={len(document.get('quase_la') or [])} (quase_la não é alerta)",
        )
        return AdapterOutput(SOURCE, FILE, len(items), tuple(alerts), tuple(skipped), notes)
