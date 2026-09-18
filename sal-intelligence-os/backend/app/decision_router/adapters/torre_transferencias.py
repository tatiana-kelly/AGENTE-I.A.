"""Investigação de transferências (FASE 4 da Torre) → alertas de ocupação por rota.

Fonte (somente leitura): o arquivo mais recente de data/transferencias_investigacao/, gerado por
snapshot/investigador_transferencias.py. Só rotas que o próprio motor priorizou (P0–P3) viram alerta;
NORMAL não é alerta. A classe de ocupação e a prioridade são do motor — o Router recalcula a faixa
com config_investigador e o adaptador registra quando as duas divergem.
"""

from app.decision_router.adapters.base import (
    PRIORITY_SEVERITY,
    AdaptedAlert,
    AdapterOutput,
    SkippedRecord,
    TorreDataReader,
    parse_torre_timestamp,
)
from app.decision_router.inputs import AlertEnvelope, EngineSignals
from app.schemas.alert import AlertBase

SOURCE = "torre.investigador_transferencias"
DIRECTORY = "transferencias_investigacao"
CONFIG_FILE = "config_investigador.json"
METRIC_ID = "ocupacao-transferencia"


class TransferInvestigationAdapter:
    name = SOURCE

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput:
        relative = reader.latest(DIRECTORY)
        if relative is None or not reader.exists(CONFIG_FILE):
            missing = relative is None and f"{DIRECTORY}/*.json" or CONFIG_FILE
            return AdapterOutput(SOURCE, relative, 0, (), notes=(f"arquivo não encontrado: {missing}",))
        document = reader.read_json(relative)
        full_occupancy = reader.read_json(CONFIG_FILE).get("ocupacao_cheio")
        generated_at = parse_torre_timestamp(document["gerado_em"])
        focus_day = document.get("dia_foco")
        routes = document.get("rotas") or []
        alerts: list[AdaptedAlert] = []
        skipped: list[SkippedRecord] = []
        for item in routes:
            route = item.get("rota")
            priority = item.get("prioridade")
            if priority not in PRIORITY_SEVERITY:
                skipped.append(SkippedRecord(SOURCE, str(route), f"prioridade do motor = {priority} (não é alerta)"))
                continue
            window = (item.get("periodo_analisado") or {}).get("janela_5du") or {}
            occupancy = window.get("ocup")
            quality = "real"
            transformations = [
                "current_value = janela_5du.ocup (o motor decide pela janela de 5 dias úteis)",
                f"reference_value = config_investigador.ocupacao_cheio ({full_occupancy})",
                f"severity pelo ordinal da prioridade do motor ({priority})",
                "concentration = a própria rota (100%)",
            ]
            if occupancy is None or full_occupancy is None:
                quality = "insufficient"
                transformations.append("janela_5du.ocup ou ocupacao_cheio ausente → source_quality=insufficient")
            gap = item.get("gap_faturamento")
            if gap is None:
                transformations.append("gap_faturamento ausente → materiality = 0")
            else:
                transformations.append("materiality = gap_faturamento do motor (R$)")
            alert = AlertBase(
                metric_id=METRIC_ID,
                title=f"Ocupação {item.get('ocupacao')} na rota {route} ({item.get('tipo_perna')})",
                period=f"5du:{focus_day}",
                current_value=float(occupancy if occupancy is not None else 0.0),
                reference_value=float(full_occupancy if full_occupancy is not None else 0.0),
                materiality=abs(float(gap)) if gap is not None else 0.0,
                severity=PRIORITY_SEVERITY[priority],
                source_quality=quality,
                concentration=[{"dimension": "rota", "value": route, "share_pct": 100}],
            )
            envelope = AlertEnvelope(
                alert=alert, engine_source=SOURCE, entity_type="rota", entity_id=str(route),
                evaluated_at=generated_at, rules_version=rules_version,
                signals=EngineSignals(single_day=False, window_class=item.get("ocupacao")),
            )
            alerts.append(AdaptedAlert(
                alert_id=f"{SOURCE}:{route}:{focus_day}",
                source=SOURCE,
                envelope=envelope,
                source_ref=f"{relative} rotas[rota={route}]",
                transformations=tuple(transformations),
                notes=(
                    (
                        f"motor: ocupacao={item.get('ocupacao')} prioridade={priority} score={item.get('score')} "
                        f"confianca={item.get('confianca')} status={item.get('status')}"
                    ),
                ),
            ))
        notes = (
            f"cobertura do motor: frete={document.get('cobertura_frete_pct')}% custo={document.get('cobertura_custo_pct')}%",
            f"validações humanas registradas: {(document.get('validacoes_humanas') or {}).get('total')}",
        )
        return AdapterOutput(SOURCE, relative, len(routes), tuple(alerts), tuple(skipped), notes)
