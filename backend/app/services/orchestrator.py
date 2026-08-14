"""Agent Orchestrator — docs/ARCHITECTURE.md item 6, fluxo de docs/AGENT_WORKFLOW.md.

Não reimplementa o raciocínio dos agentes: cada agente é chamado com o system prompt exato
de .claude/agents/<nome>.md, na ordem definida por config/domain-routing.yaml. O único código
"de negócio" aqui é a extração final estruturada (valida contra DiagnosisBase, que por sua vez
aplica as regras de .claude/rules/alert-contract.md e action-design.md em Python).
"""

from dataclasses import dataclass, field

from pydantic import ValidationError

from app.schemas.diagnosis import DiagnosisBase
from app.services.agent_loader import load_agent, load_domain_routing
from app.services.audit_trail import AuditTrail
from app.services.claude_client import ClaudeClient

_DIAGNOSIS_TOOL_SCHEMA = {
    "name": "submit_diagnosis",
    "description": (
        "Consolida a investigação em um Diagnosis estruturado, seguindo exatamente o contrato de "
        "schemas/diagnosis.schema.json: hipóteses testadas, causa provável, confiança e EXATAMENTE 3 "
        "recomendações cobrindo contenção, correção estrutural e otimização."
    ),
    "input_schema": DiagnosisBase.model_json_schema(),
}


@dataclass
class OrchestrationResult:
    case_type: str
    transcript: list[dict] = field(default_factory=list)  # [{agent, output}]
    diagnosis: DiagnosisBase | None = None
    diagnosis_error: str | None = None


class Orchestrator:
    def __init__(self, claude_client: ClaudeClient | None = None, audit_trail: AuditTrail | None = None) -> None:
        self.claude = claude_client or ClaudeClient()
        self.audit = audit_trail or AuditTrail()
        self.routing = load_domain_routing()

    def route_for(self, case_type: str) -> list[str]:
        if case_type not in self.routing:
            raise ValueError(
                f"case_type '{case_type}' não existe em config/domain-routing.yaml. "
                f"Opções: {sorted(self.routing)}"
            )
        return self.routing[case_type]

    def orchestrate(self, case_type: str, case_description: str) -> OrchestrationResult:
        agent_names = self.route_for(case_type)
        result = OrchestrationResult(case_type=case_type)

        transcript_text = f"CASO:\n{case_description}\n"
        for agent_name in agent_names:
            spec = load_agent(agent_name)
            output = self.claude.complete(system=spec.system_prompt, user_message=transcript_text)
            result.transcript.append({"agent": agent_name, "output": output})
            transcript_text += f"\n\n--- Análise de {agent_name} ---\n{output}"
            self.audit.record(
                event_type="agent_call",
                actor=agent_name,
                summary=f"case_type={case_type}",
                payload={"model": spec.model, "effort": spec.effort},
            )

        self._extract_structured_diagnosis(case_description, transcript_text, result)
        return result

    def _extract_structured_diagnosis(
        self, case_description: str, transcript_text: str, result: OrchestrationResult
    ) -> None:
        extraction_prompt = (
            "Você consolida a investigação abaixo em um Diagnosis final, chamando a tool "
            "submit_diagnosis. Não invente dado que não apareceu na investigação; se faltar, "
            "liste em missing_data. As 3 recomendações têm que cobrir exatamente containment, "
            "structural e optimization."
        )
        try:
            raw = self.claude.complete_structured(
                system=extraction_prompt,
                user_message=transcript_text,
                tool_schema=_DIAGNOSIS_TOOL_SCHEMA,
            )
            result.diagnosis = DiagnosisBase.model_validate(raw)
        except ValidationError as exc:
            result.diagnosis_error = f"saída do agente não atende ao contrato de Diagnosis: {exc}"
            self.audit.record(
                event_type="agent_call",
                actor="orchestrator.extract_structured_diagnosis",
                summary="validação de Diagnosis falhou",
                payload={"error": str(exc)},
            )
