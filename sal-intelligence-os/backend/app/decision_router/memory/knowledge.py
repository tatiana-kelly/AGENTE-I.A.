"""Classificação do conhecimento real da Torre — sem promover aprendizado a decisão.

Categorias independentes (um registro pode ter várias):
  known · false_positive · cause_known · cause_missing · decision_known · decision_approved · result_known
Regras:
- ledger "ABERTA/RESOLVIDA" = conhecido, nunca decisão;
- "RESOLVIDA" significa que a divergência sumiu, não que uma ação foi verificada;
- decisão só é conhecida quando a fonte registra validação/feedback humano; aprovada só se aceita;
- resultado só é conhecido quando há verificação explícita (não existe hoje na Torre).
"""

from dataclasses import dataclass

from app.decision_router.inputs import MemoryEntry


@dataclass(frozen=True)
class KnowledgeStatus:
    source: str
    known: bool
    false_positive: bool
    cause_known: bool
    cause_missing: bool
    decision_known: bool
    decision_approved: bool
    result_known: bool
    evidence: str

    def as_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


def classify_ledger_entry(entry: MemoryEntry | None) -> KnowledgeStatus:
    if entry is None:
        return KnowledgeStatus("aprendizado_agentes.json", False, False, False, False, False, False, False,
                               "sem registro no aprendizado")
    return KnowledgeStatus(
        source="aprendizado_agentes.json",
        known=True,
        false_positive=entry.false_positive_active,
        cause_known=bool(entry.causa),
        cause_missing=not entry.causa,
        decision_known=False,
        decision_approved=False,
        result_known=False,
        evidence=f"status={entry.status} causa={'sim' if entry.causa else 'ausente'} ({entry.source_ref})",
    )


def classify_transfer_route(route: dict, validations: dict | None) -> KnowledgeStatus:
    feedback = route.get("feedback_humano")
    decision_known = bool(feedback)
    decision_approved = bool(feedback) and str((feedback or {}).get("decisao", "")).lower() in {"aceita", "aprovada"}
    return KnowledgeStatus(
        source="transferencias_investigacao",
        known=True,
        false_positive=False,
        cause_known=False,
        cause_missing=True,
        decision_known=decision_known,
        decision_approved=decision_approved,
        result_known=False,
        evidence=(
            f"status={route.get('status')} feedback_humano={'presente' if feedback else 'nulo'} "
            f"validacoes_humanas_total={(validations or {}).get('total')}"
        ),
    )
