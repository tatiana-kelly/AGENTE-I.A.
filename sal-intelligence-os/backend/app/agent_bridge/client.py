"""Cliente SAL OS → POST /v1/agent-runs.

Garantias desta camada:
- assina cada requisição com SAL-HMAC-SHA256 sobre os bytes exatos enviados;
- gera idempotency_key determinística por caso+tentativa (reenvio não duplica execução);
- trata 400/401/403/409/422/429/502/504 com exceções tipadas — nenhum erro vira sucesso;
- nunca escreve segredo, assinatura ou cabeçalho de autorização em log ou mensagem de erro;
- não converte investigação em decisão: devolve AgentRunResult e para por aí.
"""

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.agent_bridge.contract import (
    PROTOCOL_VERSION,
    AgentAuthority,
    AgentRunRequest,
    AgentRunResult,
    AuthorizedContext,
    Evidence,
    ExecutionLimits,
    OutputContract,
    ReviewPolicy,
)
from app.agent_bridge.signing import authorization_header, sign

logger = logging.getLogger(__name__)

AGENT_RUNS_PATH = "/v1/agent-runs"
AGENT_RUNS_IDENTITY_PATH = "/v1/agent-runs/identity"
PROTOCOL_HEADER = "X-SAL-Protocol"
RESPONSE_SIGNATURE_HEADER = "X-SAL-Response-Signature"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_LIMITS = ExecutionLimits(
    timeout_seconds=240, max_attempts=3, max_cost_usd_per_call=10.0, max_cost_usd_per_job=100.0
)


class AgentRunError(RuntimeError):
    """Falha de agent-run. A mensagem nunca contém segredo, assinatura ou corpo assinado."""

    def __init__(
        self, status_code: int, code: str, detail: str, *, run_id: str | None = None, usage: tuple[dict, ...] = (),
    ) -> None:
        super().__init__(f"agent-run falhou ({status_code}/{code}): {detail}")
        self.status_code = status_code
        self.code = code
        self.detail = detail
        # Fase 5G: uso real de provider também existe em execução rejeitada; sem isso a auditoria mostrava 0.
        self.run_id = run_id
        self.usage = usage


class AgentRunRequestInvalid(AgentRunError):
    """400 — o contrato foi violado antes de qualquer provider."""


class AgentRunUnauthorized(AgentRunError):
    """401 — assinatura ausente, inválida, expirada ou repetida."""


class AgentRunForbidden(AgentRunError):
    """403 — principal sem capability agent_run no projeto."""


class AgentRunConflict(AgentRunError):
    """409 — mesma idempotency_key com corpo diferente."""


class AgentRunOutputRejected(AgentRunError):
    """422 — o output não passou no contrato de investigação."""


class AgentRunBudgetExceeded(AgentRunError):
    """429 — bloqueado pelo CostController."""


class AgentRunProviderFailure(AgentRunError):
    """502 — provider e fallback falharam."""


class AgentRunTimeout(AgentRunError):
    """504 — tempo limite excedido."""


class AgentRunIdentityError(AgentRunError):
    """O servidor não provou ser o AI Orchestrator (sem prova HMAC ou resposta sem assinatura válida).

    Levantada ANTES de enviar qualquer dado de caso quando o handshake falha — é o que impede o SAL OS de
    entregar um payload a qualquer processo que esteja ocupando a porta configurada.
    """


_ERRORS: dict[int, type[AgentRunError]] = {
    400: AgentRunRequestInvalid,
    401: AgentRunUnauthorized,
    403: AgentRunForbidden,
    405: AgentRunRequestInvalid,
    409: AgentRunConflict,
    413: AgentRunRequestInvalid,
    415: AgentRunRequestInvalid,
    422: AgentRunOutputRejected,
    429: AgentRunBudgetExceeded,
    502: AgentRunProviderFailure,
    503: AgentRunProviderFailure,
    504: AgentRunTimeout,
}


@dataclass(frozen=True)
class AgentRunClientConfig:
    base_url: str
    principal: str
    project: str
    secret: str = field(repr=False)  # fora do repr: logar a config nunca expõe o segredo

    def __post_init__(self) -> None:
        validate_base_url(self.base_url)
        if len(self.secret) < 32:
            raise ValueError("AGENT_RUN_HMAC_SECRET ausente ou curto demais (mínimo 32 caracteres).")
        if ":" not in self.principal:
            raise ValueError("principal deve ter a forma <user|service|agent>:<id>.")


def validate_base_url(base_url: str) -> None:
    """URL do Orchestrator: só origem (esquema + host + porta). HTTP sem TLS apenas em loopback."""
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("base_url do Orchestrator inválida: use http(s)://host[:porta].")
    if parts.username or parts.password:
        raise ValueError("base_url do Orchestrator não pode conter credenciais.")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError("base_url do Orchestrator deve ser só a origem, sem caminho, query ou fragmento.")
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK_HOSTS:
        raise ValueError("HTTP sem TLS só é aceito em loopback; use https para o Orchestrator remoto.")


class AgentRunNotConfigured(RuntimeError):
    """ORCHESTRATOR_BASE_URL ou AGENT_RUN_HMAC_SECRET ausentes: a ponte não é construída (fail-closed)."""


def config_from_settings(settings=None) -> AgentRunClientConfig:
    """Constrói a configuração a partir de app.core.config — nunca de valores embutidos no código."""
    from app.core.config import get_settings

    settings = settings or get_settings()
    missing = [
        name for name, value in (
            ("ORCHESTRATOR_BASE_URL", settings.orchestrator_base_url),
            ("AGENT_RUN_HMAC_SECRET", settings.agent_run_hmac_secret),
        ) if not value
    ]
    if missing:
        raise AgentRunNotConfigured(f"variáveis ausentes: {', '.join(missing)}")
    return AgentRunClientConfig(
        base_url=settings.orchestrator_base_url,
        principal=settings.agent_run_principal,
        project=settings.agent_run_project,
        secret=settings.agent_run_hmac_secret,
    )


def idempotency_key_for(*, case_id: str, fingerprint: str, agent: str, attempt: int = 1) -> str:
    """Determinística: o mesmo caso, com a mesma evidência e o mesmo agente, não executa duas vezes."""
    digest = hashlib.sha256(f"{case_id}|{fingerprint}|{agent}|{attempt}".encode()).hexdigest()
    return f"salos-{digest[:48]}"


def build_investigation_request(
    *,
    config: AgentRunClientConfig,
    case_id: str,
    fingerprint: str,
    agent: str,
    agent_version: str,
    task: str,
    context_files: tuple[str, ...],
    evidence: tuple[Evidence, ...],
    profile: str = "balanced",
    attempt: int = 1,
    business_data: dict | None = None,
    previous_results: tuple[str, ...] = (),
    limits: ExecutionLimits = DEFAULT_LIMITS,
    review: ReviewPolicy | None = None,
    authority: AgentAuthority | None = None,
) -> AgentRunRequest:
    return AgentRunRequest(
        request_id=str(uuid.uuid4()),
        idempotency_key=idempotency_key_for(case_id=case_id, fingerprint=fingerprint, agent=agent, attempt=attempt),
        principal=config.principal,
        project=config.project,
        agent=agent,
        agent_version=agent_version,
        profile=profile,  # type: ignore[arg-type]
        task=task,
        authorized_context=AuthorizedContext(project=config.project, files=context_files),
        evidence=evidence,
        previous_results=previous_results,
        business_data=business_data or {},
        execution_limits=limits,
        output_contract=OutputContract(),
        review_policy=review or ReviewPolicy(),
        agent_authority=authority or AgentAuthority(),
    )


def serialize_request(request: AgentRunRequest) -> str:
    """Corpo exato que será assinado. Campos opcionais ausentes são OMITIDOS, nunca enviados como null:
    o contrato do Orchestrator aceita campo ausente, mas recusa null (ex.: quality.completeness_pct)."""
    return json.dumps(request.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"))


def _failure_reason(payload: dict) -> tuple[str, str]:
    """Falhas do runner (422/429/502/504) vêm como resposta COMPLETA do agent-run, não como {error, detail}.
    Extrai o status e o motivo real para que a falha nunca apareça como "unknown"."""
    if "status" in payload and "output_validation" in payload:
        providers = payload.get("providers") or {}
        reasons = [str((payload.get("output_validation") or {}).get("reason", ""))]
        if providers.get("primary_failure"):
            reasons.append(f"primário {providers.get('primary')}: {providers['primary_failure']}")
        if providers.get("fallback_result"):
            reasons.append(f"fallback {providers.get('fallback_provider')}: {providers['fallback_result']}")
        detail = " | ".join(reason for reason in dict.fromkeys(reasons) if reason)
        return str(payload["status"]), detail[:1000]
    return str(payload.get("error", "unknown")), str(payload.get("detail", ""))[:1000]


def _response_canonical(nonce: str, body: bytes) -> str:
    return f"{PROTOCOL_VERSION}\nresponse\n{nonce}\n{hashlib.sha256(body).hexdigest()}"


def _identity_canonical(challenge: str) -> str:
    return f"{PROTOCOL_VERSION}\nidentity\n{challenge}"


class AgentRunClient:
    """Cliente com autenticação MÚTUA: o SAL OS prova quem é (HMAC) e exige que o servidor prove o mesmo.

    Não confia em um processo só porque ele atende na porta configurada: antes do primeiro envio faz o
    handshake de identidade (só um desafio aleatório trafega, nenhum dado de caso), e toda resposta a uma
    requisição autenticada precisa vir assinada e amarrada ao nonce daquela requisição.
    """

    def __init__(self, config: AgentRunClientConfig, transport: httpx.BaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport
        self._identity_verified = False

    def _http(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self._config.base_url, transport=self._transport, timeout=timeout)

    def _signed_post(self, client: httpx.Client, path: str, raw_body: str) -> tuple[httpx.Response, str]:
        nonce = uuid.uuid4().hex
        header = authorization_header(
            secret=self._config.secret, method="POST", path=path, principal=self._config.principal,
            raw_body=raw_body, timestamp=datetime.now(UTC), nonce=nonce,
        )
        response = client.post(
            path, content=raw_body.encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": header},
        )
        return response, nonce

    def _signature_valid(self, response: httpx.Response, nonce: str) -> bool:
        received = response.headers.get(RESPONSE_SIGNATURE_HEADER, "")
        expected = sign(self._config.secret, _response_canonical(nonce, response.content))
        return bool(received) and hmac.compare_digest(received, expected)

    def verify_identity(self) -> None:
        """Prova, antes de qualquer envio de caso, que o servidor possui o segredo compartilhado."""
        if self._identity_verified:
            return
        challenge = secrets.token_urlsafe(32)
        raw_body = json.dumps({"challenge": challenge}, separators=(",", ":"))
        try:
            with self._http(timeout=15) as client:
                response, nonce = self._signed_post(client, AGENT_RUNS_IDENTITY_PATH, raw_body)
        except httpx.TimeoutException as error:
            raise AgentRunTimeout(504, "identity_timeout", "Tempo limite no handshake de identidade.") from error
        except httpx.HTTPError as error:
            raise AgentRunProviderFailure(502, "transport_error", type(error).__name__) from error

        speaks_protocol = response.headers.get(PROTOCOL_HEADER) == PROTOCOL_VERSION
        if response.status_code in (401, 403) and speaks_protocol:
            # O Orchestrator respondeu, mas recusou NOSSA credencial (segredo, nonce ou principal).
            payload = self._decode(response)
            raise _ERRORS[response.status_code](
                response.status_code, str(payload.get("error", "unknown")), str(payload.get("detail", "")),
            )
        if response.status_code != 200 or not speaks_protocol:
            raise AgentRunIdentityError(
                response.status_code, "identity_mismatch",
                "o servidor não respondeu como AI Orchestrator (sal.agent-run/1.0); nenhum dado de caso foi enviado.",
            )
        if not self._signature_valid(response, nonce):
            raise AgentRunIdentityError(401, "identity_unsigned", "resposta de identidade sem assinatura válida.")
        body = self._decode(response)
        proof = str(body.get("proof", ""))
        if not proof or not hmac.compare_digest(proof, sign(self._config.secret, _identity_canonical(challenge))):
            raise AgentRunIdentityError(401, "identity_proof_invalid", "prova de identidade inválida.")
        self._identity_verified = True
        logger.info("identidade do AI Orchestrator confirmada", extra={"base_url": self._config.base_url})

    def run(self, request: AgentRunRequest, *, timeout_seconds: float | None = None) -> AgentRunResult:
        self.verify_identity()  # nenhum dado de caso sai antes disto
        raw_body = serialize_request(request)
        started = datetime.now(UTC)
        logger.info(
            "agent-run enviado",  # sem segredo, sem assinatura, sem corpo
            extra={"request_id": request.request_id, "agent": request.agent, "project": request.project},
        )
        try:
            with self._http(timeout=timeout_seconds or request.execution_limits.timeout_seconds) as client:
                response, nonce = self._signed_post(client, AGENT_RUNS_PATH, raw_body)
        except httpx.TimeoutException as error:
            raise AgentRunTimeout(504, "client_timeout", "Tempo limite do cliente excedido.") from error
        except httpx.HTTPError as error:
            raise AgentRunProviderFailure(502, "transport_error", type(error).__name__) from error

        # Sucesso SEMPRE exige assinatura válida: é o único caminho pelo qual um resultado entra no SAL OS.
        # Erro pode vir sem assinatura (falhas de autenticação acontecem antes de o servidor saber quem somos),
        # mas uma assinatura PRESENTE e errada denuncia servidor impostor.
        has_signature = RESPONSE_SIGNATURE_HEADER in response.headers
        signed = self._signature_valid(response, nonce)
        if (response.status_code < 400 and not signed) or (has_signature and not signed):
            raise AgentRunIdentityError(
                response.status_code, "response_unsigned",
                "resposta sem assinatura válida do AI Orchestrator; resultado descartado.",
            )

        payload = self._decode(response)
        if response.status_code >= 400:
            failure = _ERRORS.get(response.status_code, AgentRunError)
            code, detail = _failure_reason(payload)
            # uso só vem de corpo ASSINADO pelo Orchestrator; resposta sem assinatura não informa custo
            usage = tuple(item for item in payload.get("usage") or () if isinstance(item, dict)) if signed else ()
            run_id = payload.get("run_id") if signed and isinstance(payload.get("run_id"), str) else None
            raise failure(response.status_code, code, detail, run_id=run_id, usage=usage)

        result = AgentRunResult.model_validate(payload)
        if result.request_id != request.request_id or result.protocol_version != PROTOCOL_VERSION:
            raise AgentRunIdentityError(200, "response_mismatch", "resposta não corresponde à requisição enviada.")
        logger.info(
            "agent-run concluído",
            extra={
                "request_id": result.request_id,
                "run_id": result.run_id,
                "status": result.status,
                "replayed": result.replayed,
                "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            },
        )
        return result

    @staticmethod
    def _decode(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError:
            return {"error": "invalid_response", "detail": "resposta não é JSON"}
        return body if isinstance(body, dict) else {"error": "invalid_response", "detail": "resposta não é objeto"}
