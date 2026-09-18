"""Política do Decision Router — mapeamentos, faixas e limites, cada um com a origem citada.

Nada aqui altera os ativos existentes: o catálogo de agentes vem de config/domain-routing.yaml
(via agent_loader) e os limites de qualidade/confiança vêm de config/priority-scoring.yaml
(via PriorityEngine). Os limites da Torre são COPIADOS com referência à origem porque a Torre não
vive neste repositório; um adaptador futuro deve carregá-los da fonte e este arquivo ficar só com o
mapeamento. Status das decisões de negócio (pacote B4–B7, ainda sem resposta):
- correspondência ALTA: utilizável;
- correspondência MÉDIA: NÃO confirmada → tratada como UNKNOWN na seleção de agentes;
- faixa pendente de aprovação: MISSING (bloqueia reuso e playbook).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal

from app.decision_router.contract import UNKNOWN_CASE_TYPE, MappingConfidence
from app.services.agent_loader import load_domain_routing
from app.services.priority_engine import PriorityEngine

Granularity = Literal["daily", "monthly", "window_5du", "window_60d", "unknown"]
BandKind = Literal["metric_definition", "engine_classes", "reference_threshold", "engine_category", "missing"]

INVESTIGATOR = "investigador"
CHALLENGER = "provocador"
NON_SPECIALIST_AGENTS = frozenset({INVESTIGATOR, CHALLENGER, "conselheiro-executivo", "solucoes-acoes-praticas"})


@dataclass(frozen=True)
class MetricThresholds:
    """Meta/aviso/crítico de uma MetricDefinition. Valores com source='mock' nunca viram faixa (B6.4)."""

    target: float
    warning: float
    critical: float
    source: str
    materiality_min: float | None = None
    rule_ref: str = "MetricDefinition.target/warning_threshold/critical_threshold"


@dataclass(frozen=True)
class BandClass:
    label: str
    lower: float
    upper: float | None  # intervalo [lower, upper)


@dataclass(frozen=True)
class AlertThreshold:
    rule_ref: str
    min_abs_delta: float | None = None
    min_abs_pct: float | None = None
    min_current_value: float | None = None
    min_materiality: float | None = None
    above_entity_reference: bool = False


@dataclass(frozen=True)
class CoverageRule:
    scope: str
    min_pct: float
    missing_evidence_template: str
    evidence_sources: tuple[str, ...]
    rule_ref: str


@dataclass(frozen=True)
class MetricPolicy:
    metric_id: str
    case_type: str
    mapping_confidence: MappingConfidence
    mapping_confirmed: bool
    granularity: Granularity
    band_kind: BandKind
    mapping_ref: str
    thresholds: MetricThresholds | None = None
    engine_classes: Mapping[str, tuple[BandClass, ...]] = field(default_factory=lambda: MappingProxyType({}))
    engine_classes_ref: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    reference_by_entity: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    reference_default: float | None = None
    reference_ref: str | None = None
    alert_threshold: AlertThreshold | None = None
    coverage_rule: CoverageRule | None = None
    window_rule_ref: str | None = None
    memory_tolerance_pct: float | None = None
    memory_tolerance_ref: str | None = None
    specialists: tuple[str, ...] = ()
    approval_flags: tuple[str, ...] = ()
    missing_evidence_on_quality: tuple[str, ...] = ()

    @property
    def routable(self) -> bool:
        return self.case_type != UNKNOWN_CASE_TYPE and self.mapping_confirmed


@dataclass(frozen=True)
class ReusePolicy:
    """Parâmetros de reuso. DEFAULT segue as condições da especificação do Router (F06 reutiliza com uma
    decisão aprovada e verificada). B7_RECOMMENDED é o preset conservador do pacote B7, pendente de aprovação."""

    name: str
    min_diagnosis_confidence: float
    first_reuse_min_approved_decisions: int
    first_reuse_min_verified_ok: int
    learning_min_ratio: float
    daily_validity_days: int
    daily_validity_ref: str
    approved: bool


@dataclass(frozen=True)
class RouterPolicy:
    version: str
    metrics: Mapping[str, MetricPolicy]
    routing: Mapping[str, tuple[str, ...]]
    minimum_data_quality: int
    reuse: ReusePolicy
    reserved_ceiling_usd_per_call: float | None = None

    def metric(self, metric_id: str) -> MetricPolicy:
        known = self.metrics.get(metric_id)
        if known is not None:
            return known
        return MetricPolicy(
            metric_id=metric_id,
            case_type=UNKNOWN_CASE_TYPE,
            mapping_confidence="UNKNOWN",
            mapping_confirmed=False,
            granularity="unknown",
            band_kind="missing",
            mapping_ref="métrica sem correspondência na política",
        )

    def with_thresholds(self, metric_id: str, thresholds: MetricThresholds) -> "RouterPolicy":
        metrics = dict(self.metrics)
        metrics[metric_id] = replace(metrics[metric_id], thresholds=thresholds)
        return replace(self, metrics=MappingProxyType(metrics))

    def with_reuse(self, reuse: ReusePolicy) -> "RouterPolicy":
        return replace(self, reuse=reuse)


INVESTIGADOR_TRANSFERENCIAS = "torre.investigador_transferencias"
MOTOR_SNAPSHOT_PAINEL = "torre.motor_snapshot_painel"

_CONFIG_INVESTIGADOR = "Torre data/config_investigador.json"
_CONFIG_OPERACIONAL = "Torre snapshot/config_operacional.py"


def _default_metrics() -> dict[str, MetricPolicy]:
    return {
        "margem-bruta": MetricPolicy(
            metric_id="margem-bruta",
            case_type="dre_margin_cash",
            mapping_confidence="ALTA",
            mapping_confirmed=True,
            granularity="monthly",
            band_kind="metric_definition",
            mapping_ref="scripts/run_dre_case.py → orchestrate('dre_margin_cash')",
            thresholds=None,  # única MetricDefinition existente é mock (seed_mock_data.py) → MISSING até haver real
            specialists=("financeiro-dre", "custos-orcamento-roi"),
            missing_evidence_on_quality=("DRE real por filial/linha",),
        ),
        "ocupacao-transferencia": MetricPolicy(
            metric_id="ocupacao-transferencia",
            case_type="transfer",
            mapping_confidence="ALTA",
            mapping_confirmed=True,
            granularity="window_5du",
            band_kind="engine_classes",
            mapping_ref="Torre snapshot/investigador_transferencias.py (malha de transferências)",
            engine_classes=MappingProxyType(
                {
                    INVESTIGADOR_TRANSFERENCIAS: (
                        BandClass("BAIXA", 0.0, 50.0),
                        BandClass("MODERADA", 50.0, 70.0),
                        BandClass("ALTA", 70.0, 85.0),
                        BandClass("CHEIO", 85.0, None),
                    ),
                    # rótulo "ALTA" aqui significa ociosidade alta — nunca comparar entre motores (B5)
                    MOTOR_SNAPSHOT_PAINEL: (
                        BandClass("ALTA", 0.0, 60.0),
                        BandClass("MODERADA", 60.0, 85.0),
                        BandClass("ADEQUADA", 85.0, None),
                    ),
                }
            ),
            engine_classes_ref=MappingProxyType(
                {
                    INVESTIGADOR_TRANSFERENCIAS: f"{_CONFIG_INVESTIGADOR} classes_ocupacao",
                    MOTOR_SNAPSHOT_PAINEL: f"{_CONFIG_OPERACIONAL} classificar_ocupacao",
                }
            ),
            window_rule_ref="config_investigador.janela_principal_dias_uteis=5",
            specialists=("transferencia",),
        ),
        "custo-por-cte-base": MetricPolicy(
            metric_id="custo-por-cte-base",
            case_type="delivery",
            mapping_confidence="ALTA",
            mapping_confirmed=True,
            granularity="monthly",
            band_kind="reference_threshold",
            mapping_ref="Torre snapshot/motor_snapshot_painel.py:2120-2160 (dataset DS_ENTREGA)",
            reference_by_entity=MappingProxyType({"BHE": 22.0, "DIE": 22.0, "VGE": 22.0}),
            reference_default=25.0,
            reference_ref=f"{_CONFIG_OPERACIONAL} ALERTAS_CUSTO_CTE / ALERTA_CUSTO_CTE_DEFAULT",
            alert_threshold=AlertThreshold(
                rule_ref="motor_snapshot_painel.py:2161 custo_cte > alerta_cte", above_entity_reference=True
            ),
            coverage_rule=CoverageRule(
                scope="custo_performance",
                min_pct=80.0,
                missing_evidence_template="KPI de performance por base {entity_id} completo",
                evidence_sources=("motor_snapshot_painel.py (bloco custo×performance)",),
                rule_ref="motor_snapshot_painel.py:2187 campos_ok >= 80% senão parcial",
            ),
            specialists=("entrega", "custos-orcamento-roi"),
        ),
        "custo-performance-base": MetricPolicy(
            metric_id="custo-performance-base",
            case_type="delivery",
            mapping_confidence="ALTA",
            mapping_confirmed=True,
            granularity="monthly",
            band_kind="engine_category",
            mapping_ref="Torre snapshot/motor_snapshot_painel.py:2163 classificar_custo_perf (DS_ENTREGA)",
            specialists=("entrega", "custos-orcamento-roi"),
        ),
        "clientes-deficitarios": MetricPolicy(
            metric_id="clientes-deficitarios",
            case_type="commercial_profitability",
            mapping_confidence="ALTA",
            mapping_confirmed=True,
            granularity="window_60d",
            band_kind="missing",  # B6.3: sem faixa de magnitude
            mapping_ref="Torre snapshot/clientes_deficitarios.py (reajuste/taxa por cliente)",
            alert_threshold=AlertThreshold(
                rule_ref="clientes_deficitarios.py MIN_RECORRENCIA=5, MIN_PREJUIZO_PERIODO=500",
                min_current_value=5.0,
                min_materiality=500.0,
            ),
            specialists=("comercial-faturamento",),
            approval_flags=("material_contract_or_payment",),
        ),
        "divergencia-custo-rota-ssw-bi": MetricPolicy(
            metric_id="divergencia-custo-rota-ssw-bi",
            case_type="technology_data",
            mapping_confidence="MEDIA",
            mapping_confirmed=False,  # B4.1 pendente
            granularity="daily",
            band_kind="missing",  # B6.1
            mapping_ref="Torre snapshot/divergencia_rota_ssw_bi.py (reconciliação SSW×BI) — MÉDIA",
            alert_threshold=AlertThreshold(
                rule_ref="divergencia_rota_ssw_bi.py LIMIAR_ABS_PADRAO=500, LIMIAR_PCT_PADRAO=5",
                min_abs_delta=500.0,
                min_abs_pct=5.0,
            ),
            memory_tolerance_pct=15.0,
            memory_tolerance_ref="aprendizado_diario_agentes.TOLERANCIA_MUDANCA_PCT=15",
            specialists=("ti-dados", "auditoria-controladoria"),
        ),
        "divergencia-card-apuracao-ssw": MetricPolicy(
            metric_id="divergencia-card-apuracao-ssw",
            case_type="technology_data",
            mapping_confidence="MEDIA",
            mapping_confirmed=False,  # B4.2 pendente
            granularity="daily",
            band_kind="missing",  # B6.2
            mapping_ref="Torre snapshot/conferir_apuracao_custo.py (card × Torre/SSW) — MÉDIA",
            alert_threshold=AlertThreshold(
                rule_ref="conferir_apuracao_custo.py LIMITE_TOTAL_RS=10000 (operador de comparação não verificado)",
                min_abs_delta=10000.0,
            ),
            specialists=("ti-dados", "auditoria-controladoria"),
        ),
        "custo-parceiros-pct-faturamento": MetricPolicy(
            metric_id="custo-parceiros-pct-faturamento",
            case_type="delivery",
            mapping_confidence="MEDIA",
            mapping_confirmed=False,  # B4.3 pendente
            granularity="daily",
            band_kind="missing",  # B6.6 pendente
            mapping_ref="Torre snapshot/alerta_custo_parceiros.py (motor Parceiros) — MÉDIA",
            specialists=("entrega",),
        ),
        "projecao-faturamento-custos-base": MetricPolicy(
            metric_id="projecao-faturamento-custos-base",
            case_type=UNKNOWN_CASE_TYPE,  # B4.4
            mapping_confidence="UNKNOWN",
            mapping_confirmed=False,
            granularity="monthly",
            band_kind="missing",  # B6.7
            mapping_ref="Torre snapshot/orquestrador_projecao.py — candidatos sem evidência explícita",
        ),
    }


def build_default_policy(priority_engine: PriorityEngine | None = None) -> RouterPolicy:
    engine = priority_engine or PriorityEngine()
    routing = {case_type: tuple(agents) for case_type, agents in load_domain_routing().items()}
    known_flags = set(engine.gates.get("human_approval_required_if", []))
    metrics = _default_metrics()
    for policy in metrics.values():
        _validate_metric(policy, routing, known_flags)
    reuse = ReusePolicy(
        name="router-spec-default",
        min_diagnosis_confidence=float(engine.gates["minimum_confidence_ready_for_decision"]),
        first_reuse_min_approved_decisions=1,
        first_reuse_min_verified_ok=1,
        learning_min_ratio=1.0,
        daily_validity_days=30,
        daily_validity_ref="config_investigador.janela_tendencia_dias=30",
        approved=False,
    )
    return RouterPolicy(
        version="router-policy/1",
        metrics=MappingProxyType(metrics),
        routing=MappingProxyType(routing),
        minimum_data_quality=int(engine.gates["minimum_data_quality"]),
        reuse=reuse,
    )


def b7_recommended_reuse(base: ReusePolicy) -> ReusePolicy:
    """Preset conservador do pacote B7 (pendente de aprovação)."""
    return replace(
        base,
        name="b7-recommended",
        first_reuse_min_approved_decisions=2,
        first_reuse_min_verified_ok=2,
        learning_min_ratio=1.0,
        approved=False,
    )


def _validate_metric(policy: MetricPolicy, routing: Mapping[str, tuple[str, ...]], known_flags: set[str]) -> None:
    if policy.case_type != UNKNOWN_CASE_TYPE and policy.case_type not in routing:
        raise ValueError(f"{policy.metric_id}: case_type '{policy.case_type}' não existe em domain-routing.yaml")
    if policy.case_type != UNKNOWN_CASE_TYPE:
        catalog = set(routing[policy.case_type])
        invalid = [name for name in policy.specialists if name not in catalog or name in NON_SPECIALIST_AGENTS]
        if invalid:
            raise ValueError(f"{policy.metric_id}: especialistas fora da rota {policy.case_type}: {invalid}")
        if not policy.specialists:
            raise ValueError(f"{policy.metric_id}: métrica roteável exige ao menos 1 especialista")
    unknown_flags = [flag for flag in policy.approval_flags if flag not in known_flags]
    if unknown_flags:
        raise ValueError(f"{policy.metric_id}: marcas fora de priority-scoring.yaml: {unknown_flags}")
