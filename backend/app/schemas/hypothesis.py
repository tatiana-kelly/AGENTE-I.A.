from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import HypothesisStatus


class HypothesisBase(BaseModel):
    """Espelha schemas/hypothesis.schema.json. Regra do Investigador: nunca tratar correlação como causa provada."""

    statement: str
    favorable_evidence: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=100)
    status: HypothesisStatus = HypothesisStatus.UNTESTED

    @model_validator(mode="after")
    def confirmed_or_refuted_needs_contrary_evidence(self) -> "HypothesisBase":
        # docs/AGENT_WORKFLOW.md N4: testar hipótese = evidência favorável, CONTRÁRIA, dado faltante e
        # contrafactual. Uma hipótese "confirmada" sem nunca ter sido contestada é só uma opinião confirmada
        # por si mesma — exatamente o "causa única prematura" que .claude/rules/diagnostic-quality.md proíbe.
        if self.status in (HypothesisStatus.CONFIRMED, HypothesisStatus.REFUTED) and not self.contrary_evidence:
            raise ValueError(
                f"hipótese com status '{self.status}' precisa registrar contrary_evidence "
                "(evidência contrária testada), não só favorable_evidence"
            )
        return self


class HypothesisCreate(HypothesisBase):
    diagnosis_id: str


class HypothesisOut(HypothesisBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    diagnosis_id: str
