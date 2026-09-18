"""Adaptadores read-only: saídas reais da Torre → AlertEnvelope (shadow mode do Decision Router)."""

from app.decision_router.adapters.base import AdaptedAlert, AdapterOutput, SkippedRecord, TorreDataReader
from app.decision_router.adapters.torre_apuracao import (
    ApuracaoCardDivergenceAdapter,
    ReconciliationTorreApuracaoAdapter,
)
from app.decision_router.adapters.torre_clientes import DeficitClientsAdapter
from app.decision_router.adapters.torre_custos import CostPerCteAdapter, CostPerformanceAdapter
from app.decision_router.adapters.torre_divergencia import SswBiRouteDivergenceAdapter, ledger_memory_entries
from app.decision_router.adapters.torre_projecao import ProjectionAlertAdapter
from app.decision_router.adapters.torre_transferencias import TransferInvestigationAdapter


def default_torre_adapters() -> tuple:
    return (
        SswBiRouteDivergenceAdapter(),
        ApuracaoCardDivergenceAdapter(),
        ReconciliationTorreApuracaoAdapter(),
        TransferInvestigationAdapter(),
        CostPerCteAdapter(),
        CostPerformanceAdapter(),
        ProjectionAlertAdapter(),
        DeficitClientsAdapter(),
    )


__all__ = [
    "AdaptedAlert",
    "AdapterOutput",
    "ApuracaoCardDivergenceAdapter",
    "CostPerCteAdapter",
    "CostPerformanceAdapter",
    "DeficitClientsAdapter",
    "ProjectionAlertAdapter",
    "ReconciliationTorreApuracaoAdapter",
    "SkippedRecord",
    "SswBiRouteDivergenceAdapter",
    "TorreDataReader",
    "TransferInvestigationAdapter",
    "default_torre_adapters",
    "ledger_memory_entries",
]
