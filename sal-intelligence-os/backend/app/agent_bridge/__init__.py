"""Ponte SAL Intelligence OS → AI Orchestrator (/v1/agent-runs, sal.agent-run/1.0).

O SAL OS envia investigação e recebe insumo estruturado. Nada que volta daqui vira diagnóstico aprovado,
recomendação aceita, decisão, ação ou aprendizado: essas transições continuam no ciclo governado.
"""

from app.agent_bridge.client import (
    AgentRunBudgetExceeded,
    AgentRunClient,
    AgentRunClientConfig,
    AgentRunConflict,
    AgentRunError,
    AgentRunForbidden,
    AgentRunIdentityError,
    AgentRunNotConfigured,
    AgentRunOutputRejected,
    AgentRunProviderFailure,
    AgentRunRequestInvalid,
    AgentRunTimeout,
    AgentRunUnauthorized,
    build_investigation_request,
    config_from_settings,
    idempotency_key_for,
)
from app.agent_bridge.contract import (
    PROTOCOL_VERSION,
    AgentAuthority,
    AgentRunRequest,
    AgentRunResult,
    Evidence,
    EvidenceQuality,
    InvestigationOutput,
)

__all__ = [
    "PROTOCOL_VERSION",
    "AgentAuthority",
    "AgentRunBudgetExceeded",
    "AgentRunClient",
    "AgentRunClientConfig",
    "AgentRunConflict",
    "AgentRunError",
    "AgentRunForbidden",
    "AgentRunIdentityError",
    "AgentRunNotConfigured",
    "AgentRunOutputRejected",
    "AgentRunProviderFailure",
    "AgentRunRequest",
    "AgentRunRequestInvalid",
    "AgentRunResult",
    "AgentRunTimeout",
    "AgentRunUnauthorized",
    "Evidence",
    "EvidenceQuality",
    "InvestigationOutput",
    "build_investigation_request",
    "config_from_settings",
    "idempotency_key_for",
]
