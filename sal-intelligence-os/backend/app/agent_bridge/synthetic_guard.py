"""Trava para testes com IA real usando SOMENTE dados sintéticos (Fase 5G).

Envolve o AgentRunClient e valida CADA requisição antes de ela sair. Qualquer falha levanta
SyntheticGuardViolation e o provider NÃO é chamado:
- `business_data.synthetic_test` é True e toda evidência está marcada `synthetic_test=True`;
- nenhum marcador de dado real (nomes de rota/cidade reais da Torre, fornecidos pelo chamador) aparece no
  que é enviado como tarefa, evidência, dados de negócio, resultados anteriores ou consolidação;
- tamanho do corpo dentro do limite do contrato;
- orçamento dentro dos limites aprovados (por chamada e por job);
- contexto pedido é subconjunto do contexto autorizado;
- aprovar/executar sempre False (recomendar/propor é permitido desde 2026-09-19).
"""

import json
from dataclasses import dataclass

from app.agent_bridge.client import AgentRunClient, serialize_request
from app.agent_bridge.contract import LIMITS, AgentRunRequest, AgentRunResult


class SyntheticGuardViolation(RuntimeError):
    """A requisição não pode sair: ela não é comprovadamente sintética ou fere um limite."""


@dataclass(frozen=True)
class SyntheticGuardPolicy:
    real_markers: frozenset[str]            # termos reais que NUNCA podem sair (ex.: rotas e cidades da Torre)
    authorized_context: frozenset[str]      # arquivos de contexto permitidos
    max_cost_usd_per_call: float
    max_cost_usd_per_job: float
    max_body_bytes: int = LIMITS["body_bytes"]


def _scannable(request: AgentRunRequest) -> str:
    """Tudo que carrega DADO do caso (o contexto técnico autorizado é tratado à parte)."""
    parts = {
        "task": request.task,
        "evidence": [item.model_dump(mode="json") for item in request.evidence],
        "business_data": request.business_data,
        "previous_results": list(request.previous_results),
        "review_target": request.review_target.model_dump(mode="json") if request.review_target else None,
    }
    return json.dumps(parts, ensure_ascii=False).upper()


def validate_synthetic_request(request: AgentRunRequest, policy: SyntheticGuardPolicy) -> None:
    problems: list[str] = []
    if request.business_data.get("synthetic_test") is not True:
        problems.append("business_data.synthetic_test != true")
    if not request.evidence or any(item.filters.get("synthetic_test") is not True for item in request.evidence):
        problems.append("evidência sem marcação synthetic_test=true")
    text = _scannable(request)
    leaked = sorted(marker for marker in policy.real_markers if marker and marker.upper() in text)
    if leaked:
        problems.append(f"marcadores de dado real presentes: {leaked[:5]}")
    size = len(serialize_request(request).encode("utf-8"))
    if size > policy.max_body_bytes:
        problems.append(f"corpo com {size} bytes > {policy.max_body_bytes}")
    limits = request.execution_limits
    if limits.max_cost_usd_per_call > policy.max_cost_usd_per_call or limits.max_cost_usd_per_job > policy.max_cost_usd_per_job:
        problems.append("orçamento acima do aprovado")
    extra_context = sorted(set(request.authorized_context.files) - policy.authorized_context)
    if extra_context:
        problems.append(f"contexto fora do autorizado: {extra_context}")
    authority = request.agent_authority
    if authority.can_approve or authority.can_execute:  # recomendar/propor é permitido desde 2026-09-19
        problems.append("autoridade de aprovar/executar diferente de false")
    if problems:
        raise SyntheticGuardViolation("; ".join(problems))


class GuardedClient:
    """Mesma interface de AgentRunClient.run, com a trava aplicada ANTES de qualquer envio."""

    def __init__(self, client: AgentRunClient, policy: SyntheticGuardPolicy) -> None:
        self._client = client
        self._policy = policy
        self.validated: list[str] = []  # request_ids que passaram pela trava

    def run(self, request: AgentRunRequest, **kwargs) -> AgentRunResult:
        validate_synthetic_request(request, self._policy)
        self.validated.append(request.request_id)
        return self._client.run(request, **kwargs)
