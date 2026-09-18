"""FASE 5C — integração mockada SAL OS → /v1/agent-runs → provider falso → SAL OS.

Nenhuma IA real: o servidor de teste reimplementa o contrato do Orchestrator (assinatura, replay,
idempotência, permissão, contexto, contrato de saída) e responde com um provider falso.
O vetor de assinatura compartilhado prova que Python e TypeScript assinam exatamente igual.
"""

import hashlib
import hmac
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from app.agent_bridge import (
    AgentRunBudgetExceeded,
    AgentRunClient,
    AgentRunClientConfig,
    AgentRunConflict,
    AgentRunForbidden,
    AgentRunOutputRejected,
    AgentRunProviderFailure,
    AgentRunRequestInvalid,
    AgentRunTimeout,
    AgentRunUnauthorized,
    Evidence,
    EvidenceQuality,
    build_investigation_request,
    idempotency_key_for,
)
from app.agent_bridge.signing import body_hash_hex, canonical_string, sign

SECRET = "segredo-de-teste-com-mais-de-32-caracteres"
PRINCIPAL = "service:sal-intelligence-os"
PROJECT = "sal-intelligence-os"
AUTHORIZED_FILES = ("ARCHITECTURE.md", "DATA_MODEL.md")
VECTOR = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "agent_run_signature_vector.json").read_text(encoding="utf-8"))

VALID_OUTPUT = {
    "facts": ["ocupação de 17,6% na janela de 5 dias úteis"],
    "calculations": ["gap = 85 - 17,6"],
    "inferences": ["possível desbalanceamento da malha"],
    "hypotheses": [
        {
            "statement": "demanda concentrada em um sentido",
            "favorable_evidence": ["ocupação assimétrica"],
            "contrary_evidence": ["frete estável"],
            "missing_evidence": ["volume por sentido"],
            "confidence": 60,
        }
    ],
    "contradictions": [],
    "missing_data": ["custo real por viagem"],
    "evidence": ["ev-1"],
    "confidence": 55,
}


class FakeOrchestrator(BaseHTTPRequestHandler):
    """Reimplementa o contrato do Orchestrator para testar o cliente ponta a ponta, sem rede externa:
    assinatura HMAC, replay, handshake de identidade e respostas assinadas."""

    behaviour: ClassVar[dict] = {}
    state: ClassVar[dict] = {}
    _nonce: str | None = None

    def do_POST(self) -> None:  # nome exigido por BaseHTTPRequestHandler
        self._nonce = None  # só respostas após autenticação são assinadas, como no Orchestrator real
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if self.path not in ("/v1/agent-runs", "/v1/agent-runs/identity"):
            return self._json(404, {"error": "not_found", "detail": "rota inexistente"})

        auth = self.headers.get("Authorization") or ""
        parsed = dict(part.split("=", 1) for part in auth.removeprefix("SAL-HMAC-SHA256 ").split(",") if "=" in part)
        if not auth.startswith("SAL-HMAC-SHA256 ") or not {"principal", "timestamp", "nonce", "signature"} <= parsed.keys():
            return self._json(401, {"error": "malformed", "detail": "cabeçalho inválido"})

        expected = hmac.new(
            SECRET.encode(),
            canonical_string(
                method="POST", path=self.path, timestamp=parsed["timestamp"], nonce=parsed["nonce"],
                principal=parsed["principal"], body_hash=hashlib.sha256(raw.encode()).hexdigest(),
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(parsed["signature"], expected):
            return self._json(401, {"error": "signature", "detail": "assinatura inválida"})

        stamp = datetime.fromisoformat(parsed["timestamp"].replace("Z", "+00:00"))
        if abs((datetime.now(UTC) - stamp).total_seconds()) > 300:
            return self._json(401, {"error": "stale", "detail": "timestamp fora da janela"})
        if parsed["nonce"] in self.state.setdefault("nonces", set()):
            return self._json(401, {"error": "replay", "detail": "nonce já utilizado"})
        self.state["nonces"].add(parsed["nonce"])

        if parsed["principal"] not in self.behaviour.get("allowed_principals", [PRINCIPAL]):
            return self._json(403, {"error": "principal", "detail": "principal não autorizado"})

        self._nonce = parsed["nonce"]
        body = json.loads(raw)
        if self.path == "/v1/agent-runs/identity":
            self.state["identity_calls"] = self.state.get("identity_calls", 0) + 1
            proof = hmac.new(SECRET.encode(), f"sal.agent-run/1.0\nidentity\n{body['challenge']}".encode(), hashlib.sha256).hexdigest()
            return self._json(200, {"protocol_version": "sal.agent-run/1.0", "service": "ai-orchestrator",
                                    "challenge": body["challenge"], "proof": proof})

        forced = self.behaviour.get("force_status")
        if forced:
            return self._json(forced, {"error": self.behaviour.get("force_error", "forced"), "detail": "forçado no teste"})

        if body["principal"] != parsed["principal"]:
            return self._json(403, {"error": "principal_mismatch", "detail": "principal divergente"})
        if body["project"] not in self.behaviour.get("permitted_projects", [PROJECT]):
            return self._json(403, {"error": "permission_denied", "detail": "sem capability agent_run"})
        if body["protocol_version"] != "sal.agent-run/1.0" or body["permission"] != "agent_run":
            return self._json(400, {"error": "invalid_request", "detail": "contrato inválido"})

        key = body["idempotency_key"]
        request_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        stored = self.state.setdefault("runs", {}).get(key)
        if stored:
            if stored["hash"] != request_hash:
                return self._json(409, {"error": "idempotency_conflict", "detail": "corpo diferente"})
            self.state["provider_calls"] = self.state.get("provider_calls", 0)
            return self._json(200, {**stored["response"], "replayed": True})

        # "provider falso": só arquivos registrados entram no contexto; o resto vira missing_context
        registered = set(self.behaviour.get("registered_files", AUTHORIZED_FILES))
        requested = body["authorized_context"]["files"]
        files_sent = [item for item in requested if item in registered]
        missing = [item for item in requested if item not in registered]
        self.state["last_request"] = body
        self.state["provider_calls"] = self.state.get("provider_calls", 0) + 1

        output = self.behaviour.get("output", VALID_OUTPUT)
        invalid = self.behaviour.get("invalid_output", False)
        response = {
            "protocol_version": "sal.agent-run/1.0",
            "request_id": body["request_id"],
            "run_id": str(uuid.uuid4()),
            "status": "rejected_output" if invalid else "succeeded",
            "agent": body["agent"],
            "agent_version": body["agent_version"],
            "agent_authority": body["agent_authority"],
            "output": None if invalid else output,
            "output_validation": {"valid": not invalid, "reason": "ok" if not invalid else "output fora do contrato"},
            "review": {"required": True, "reviewed": True, "status": "APPROVED", "corrections": 0},
            "providers": {
                "primary": "openai",
                "fallback_triggered": self.behaviour.get("fallback", False),
                "fallback_provider": "manus" if self.behaviour.get("fallback") else None,
            },
            "usage": [{"provider": "openai", "model": "fake", "input_tokens": "unknown", "output_tokens": "unknown",
                       "total_tokens": "unknown", "estimated_cost_usd": 0.01, "reserved_cost_usd": 0.01,
                       "actual_cost_usd": "unknown", "attempt": 1, "latency_ms": 5}],
            "context": {"project": body["project"], "files_sent": files_sent, "missing_context": missing},
            "evidence_received": [item["id"] for item in body["evidence"]],
            "replayed": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if invalid:
            return self._json(422, response)
        self.state["runs"][key] = {"hash": request_hash, "response": response}
        return self._json(200, response)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-SAL-Protocol", "sal.agent-run/1.0")
        if self._nonce and not self.behaviour.get("skip_signature"):
            canonical = f"sal.agent-run/1.0\nresponse\n{self._nonce}\n{hashlib.sha256(body).hexdigest()}"
            signature = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
            if self.behaviour.get("forge_signature"):
                signature = "0" * 64
            self.send_header("X-SAL-Response-Signature", signature)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:  # silencia o log do servidor de teste
        return


@pytest.fixture()
def orchestrator():
    FakeOrchestrator.behaviour = {}
    FakeOrchestrator.state = {}
    server = HTTPServer(("127.0.0.1", 0), FakeOrchestrator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def client(orchestrator):
    config = AgentRunClientConfig(
        base_url=f"http://127.0.0.1:{orchestrator.server_address[1]}",
        principal=PRINCIPAL, project=PROJECT, secret=SECRET,
    )
    return AgentRunClient(config), config


def _evidence() -> tuple[Evidence, ...]:
    return (
        Evidence(
            id="ev-1", source="fixture-controlado", period="5du:2026-09-17",
            timestamp=datetime(2026, 9, 17, 12, tzinfo=UTC), filters={"rota": "ROTA-TESTE"},
            quality=EvidenceQuality(source_quality="real", completeness_pct=100, checks=("comparabilidade",)),
            limitations=("amostra de teste",), data={"ocupacao_pct": 17.6, "alvo_pct": 85},
        ),
    )


def _request(config, *, files=AUTHORIZED_FILES, case_id="caso-1", attempt=1):
    return build_investigation_request(
        config=config, case_id=case_id, fingerprint="sha256:fixture", agent="investigador",
        agent_version="1.0.0", task="Investigue a causa de uma divergência operacional controlada.",
        context_files=files, evidence=_evidence(), attempt=attempt,
    )


# ── assinatura ───────────────────────────────────────────────────────────────────────────────

def test_vetor_de_assinatura_compartilhado_com_o_orchestrator():
    canonical = canonical_string(
        method=VECTOR["method"], path=VECTOR["path"], timestamp=VECTOR["timestamp"],
        nonce=VECTOR["nonce"], principal=VECTOR["principal"], body_hash=body_hash_hex(VECTOR["body"]),
    )
    assert body_hash_hex(VECTOR["body"]) == VECTOR["body_hash_sha256"]
    assert sign(VECTOR["secret"], canonical) == VECTOR["expected_signature"]


def test_assinatura_valida_executa_e_devolve_output_estruturado(client):
    agent_client, config = client
    result = agent_client.run(_request(config))
    assert result.status == "succeeded"
    assert result.usable is True
    assert result.output.facts and result.output.hypotheses[0].confidence == 60
    assert result.evidence_received == ("ev-1",)


def test_assinatura_invalida_e_replay_sao_recusados(client, orchestrator):
    agent_client, config = client
    ruim = AgentRunClient(AgentRunClientConfig(
        base_url=f"http://127.0.0.1:{orchestrator.server_address[1]}", principal=PRINCIPAL,
        project=PROJECT, secret="outro-segredo-com-32-caracteres-aqui!",
    ))
    with pytest.raises(AgentRunUnauthorized):
        ruim.run(_request(config))

    # replay: mesmo nonce reaproveitado manualmente
    FakeOrchestrator.state.setdefault("nonces", set()).add("nonce-repetido")
    import app.agent_bridge.client as client_module

    original = client_module.authorization_header
    client_module.authorization_header = lambda **kwargs: original(**{**kwargs, "nonce": "nonce-repetido"})
    try:
        with pytest.raises(AgentRunUnauthorized) as error:
            agent_client.run(_request(config))
        assert error.value.code == "replay"
    finally:
        client_module.authorization_header = original


def test_principal_e_projeto_precisam_estar_autorizados(client):
    agent_client, config = client
    FakeOrchestrator.behaviour["permitted_projects"] = ["outro-projeto"]
    with pytest.raises(AgentRunForbidden) as error:
        agent_client.run(_request(config))
    assert "agent_run" in error.value.detail

    FakeOrchestrator.behaviour.clear()
    FakeOrchestrator.behaviour["allowed_principals"] = ["service:outro"]
    with pytest.raises(AgentRunForbidden):
        agent_client.run(_request(config))


# ── idempotência ─────────────────────────────────────────────────────────────────────────────

def test_idempotencia_nao_executa_duas_vezes(client):
    agent_client, config = client
    request = _request(config)
    primeiro = agent_client.run(request)
    segundo = agent_client.run(request)
    assert segundo.replayed is True
    assert segundo.run_id == primeiro.run_id
    assert FakeOrchestrator.state["provider_calls"] == 1


def test_mesma_chave_com_corpo_diferente_gera_conflito(client):
    agent_client, config = client
    agent_client.run(_request(config))
    outro = _request(config).model_copy(update={"task": "tarefa completamente diferente"})
    with pytest.raises(AgentRunConflict):
        agent_client.run(outro)


def test_idempotency_key_e_deterministica():
    mesma = idempotency_key_for(case_id="c1", fingerprint="fp", agent="investigador")
    assert mesma == idempotency_key_for(case_id="c1", fingerprint="fp", agent="investigador")
    assert mesma != idempotency_key_for(case_id="c1", fingerprint="fp", agent="investigador", attempt=2)
    assert len(mesma) >= 16


# ── contexto e evidência ─────────────────────────────────────────────────────────────────────

def test_arquivo_nao_autorizado_nao_e_enviado(client):
    agent_client, config = client
    result = agent_client.run(_request(config, files=("ARCHITECTURE.md", ".env", "MASTER_SPEC.md")))
    assert result.context["files_sent"] == ["ARCHITECTURE.md"]
    assert result.context["missing_context"] == [".env", "MASTER_SPEC.md"]
    enviado = FakeOrchestrator.state["last_request"]
    assert enviado["authorized_context"]["project"] == PROJECT


def test_evidencia_vai_estruturada_e_intacta(client):
    agent_client, config = client
    agent_client.run(_request(config))
    evidence = FakeOrchestrator.state["last_request"]["evidence"][0]
    assert evidence["source"] == "fixture-controlado"
    assert evidence["period"] == "5du:2026-09-17"
    assert evidence["quality"]["source_quality"] == "real"
    assert evidence["limitations"] == ["amostra de teste"]
    assert evidence["data"] == {"ocupacao_pct": 17.6, "alvo_pct": 85}


def test_output_contract_e_autoridade_vao_no_request(client):
    agent_client, config = client
    agent_client.run(_request(config))
    enviado = FakeOrchestrator.state["last_request"]
    assert enviado["output_contract"] == {
        "kind": "investigation", "schema_version": "sal.investigation-output/1.0", "require_json": True,
    }
    assert enviado["agent_authority"] == {
        "can_recommend": False, "can_propose": False, "can_approve": False, "can_execute": False,
    }
    assert enviado["execution_limits"]["max_cost_usd_per_call"] <= 10
    assert enviado["execution_limits"]["timeout_seconds"] <= 240


def test_autoridade_nao_pode_ser_elevada_no_contrato():
    from pydantic import ValidationError

    from app.agent_bridge.contract import AgentAuthority

    with pytest.raises(ValidationError):
        AgentAuthority(can_approve=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        AgentAuthority(can_execute=True)  # type: ignore[arg-type]


# ── respostas de erro ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (400, AgentRunRequestInvalid),
        (403, AgentRunForbidden),
        (422, AgentRunOutputRejected),
        (429, AgentRunBudgetExceeded),
        (502, AgentRunProviderFailure),
        (504, AgentRunTimeout),
    ],
)
def test_cada_status_vira_excecao_tipada(client, status, exception):
    agent_client, config = client
    FakeOrchestrator.behaviour["force_status"] = status
    with pytest.raises(exception) as error:
        agent_client.run(_request(config))
    assert error.value.status_code == status


def test_output_invalido_nao_vira_sucesso(client):
    agent_client, config = client
    FakeOrchestrator.behaviour["invalid_output"] = True
    with pytest.raises(AgentRunOutputRejected):
        agent_client.run(_request(config))


def test_fallback_e_reportado_ao_sal_os(client):
    agent_client, config = client
    FakeOrchestrator.behaviour["fallback"] = True
    result = agent_client.run(_request(config))
    assert result.providers["fallback_triggered"] is True
    assert result.providers["fallback_provider"] == "manus"


def test_timeout_do_cliente_vira_excecao(orchestrator):
    import httpx

    def travar(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout simulado")

    config = AgentRunClientConfig(
        base_url=f"http://127.0.0.1:{orchestrator.server_address[1]}", principal=PRINCIPAL,
        project=PROJECT, secret=SECRET,
    )
    with pytest.raises(AgentRunTimeout):
        AgentRunClient(config, transport=httpx.MockTransport(travar)).run(_request(config))


def test_erro_de_transporte_vira_falha_de_provider(orchestrator):
    import httpx

    def cair(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada")

    config = AgentRunClientConfig(
        base_url=f"http://127.0.0.1:{orchestrator.server_address[1]}", principal=PRINCIPAL,
        project=PROJECT, secret=SECRET,
    )
    with pytest.raises(AgentRunProviderFailure):
        AgentRunClient(config, transport=httpx.MockTransport(cair)).run(_request(config))


# ── segredo nunca vaza ───────────────────────────────────────────────────────────────────────

def test_segredo_e_assinatura_nunca_aparecem_em_log_nem_em_erro(client, caplog):
    agent_client, config = client
    with caplog.at_level(logging.DEBUG):
        agent_client.run(_request(config))
        FakeOrchestrator.behaviour["force_status"] = 401
        with pytest.raises(AgentRunUnauthorized) as error:
            agent_client.run(_request(config, case_id="caso-2"))
    registrado = " ".join(record.getMessage() + json.dumps(record.__dict__, default=str) for record in caplog.records)
    assert SECRET not in registrado
    assert "SAL-HMAC-SHA256" not in registrado
    assert SECRET not in str(error.value)


def test_configuracao_recusa_segredo_fraco_ou_url_invalida():
    with pytest.raises(ValueError):
        AgentRunClientConfig(base_url="http://x", principal=PRINCIPAL, project=PROJECT, secret="curto")
    with pytest.raises(ValueError):
        AgentRunClientConfig(base_url="ftp://x", principal=PRINCIPAL, project=PROJECT, secret=SECRET)
    with pytest.raises(ValueError):
        AgentRunClientConfig(base_url="http://x", principal="sem-tipo", project=PROJECT, secret=SECRET)


# ── governança: investigação não vira decisão ────────────────────────────────────────────────

def test_investigacao_nao_vira_decisao_nem_acao(client):
    """O insumo do agente não tem autoridade: não existe caminho de código que o transforme em decisão."""
    from app.decision_cycle.governance import GovernanceViolation
    from app.decision_cycle.states import CaseState, IllegalTransition, assert_transition

    agent_client, config = client
    result = agent_client.run(_request(config))

    # o output não possui — por contrato — nenhum campo de decisão, ação ou verificação
    campos = set(result.output.model_dump().keys())
    assert campos.isdisjoint({"approved_decision", "execute_action", "verified_ok", "decision", "action"})
    assert result.agent_authority.can_approve is False
    assert result.agent_authority.can_execute is False

    # investigação não pula etapas do ciclo governado
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.INVESTIGATING, CaseState.APPROVED)
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.INVESTIGATING, CaseState.ACTION_PENDING)
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.DIAGNOSED, CaseState.APPROVED)

    # e uma máquina não aprova o que ela mesma produziu
    from app.core.rbac import Role
    from app.decision_cycle.approval import ApprovalService
    from app.decision_cycle.events import CycleEventRecorder
    from app.decision_cycle.governance import human, machine
    from app.services.audit_trail import AuditTrail

    service = ApprovalService(CycleEventRecorder(AuditTrail(Path("/dev/null"))))
    assert machine("investigador").kind.value == "machine"
    assert human("tatiana", Role.DIRETORIA).kind.value == "human"
    with pytest.raises((GovernanceViolation, AttributeError, TypeError)):
        service.approve_proposal(None, machine("investigador"), "auto", "rec", 1)  # type: ignore[arg-type]


def test_resultado_so_e_aproveitavel_quando_validado(client):
    agent_client, config = client
    result = agent_client.run(_request(config))
    assert result.usable is True
    nao_validado = result.model_copy(update={"output_validation": {"valid": False, "reason": "x"}})
    assert nao_validado.usable is False


# ── configuração por ambiente (Fase 5D) ──────────────────────────────────────────────────────

def test_config_vem_do_ambiente_e_falha_fechado_sem_variaveis():
    from app.agent_bridge import AgentRunNotConfigured, config_from_settings
    from app.core.config import Settings

    with pytest.raises(AgentRunNotConfigured) as error:
        config_from_settings(Settings(_env_file=None))
    assert "ORCHESTRATOR_BASE_URL" in str(error.value) and "AGENT_RUN_HMAC_SECRET" in str(error.value)

    config = config_from_settings(Settings(
        _env_file=None, orchestrator_base_url="http://127.0.0.1:3000", agent_run_hmac_secret=SECRET,
    ))
    assert config.principal == "service:sal-intelligence-os" and config.project == "sal-intelligence-os"


def test_repr_da_configuracao_nunca_mostra_o_segredo():
    config = AgentRunClientConfig(base_url="http://127.0.0.1:3000", principal=PRINCIPAL, project=PROJECT, secret=SECRET)
    assert SECRET not in repr(config)
    assert SECRET not in str(config)


def test_corpo_serializado_nunca_envia_null():
    """Regressão do pré-voo 5D: completeness_pct=None virava null e o Orchestrator recusava com 400."""
    from app.agent_bridge.client import serialize_request

    config = AgentRunClientConfig(base_url="http://127.0.0.1:3000", principal=PRINCIPAL, project=PROJECT, secret=SECRET)
    evidence = (Evidence(id="ev-x", source="s", period="P", timestamp=datetime(2026, 9, 17, tzinfo=UTC),
                         quality=EvidenceQuality(source_quality="sintetica"), data={"a": 1}),)
    body = serialize_request(_request(config).model_copy(update={"evidence": evidence}))
    assert "null" not in body
    assert "completeness_pct" not in json.loads(body)["evidence"][0]["quality"]



# ── identidade do Orchestrator (Fase 5E) ─────────────────────────────────────────────────────

def test_handshake_de_identidade_acontece_antes_do_primeiro_envio(client):
    agent_client, config = client
    agent_client.run(_request(config))
    agent_client.run(_request(config, case_id="caso-2"))
    assert FakeOrchestrator.state["identity_calls"] == 1  # uma vez por cliente, antes de qualquer caso


def test_servidor_impostor_nunca_recebe_dado_de_caso():
    """Regressão do incidente 5D: um serviço qualquer na porta (ex.: bridge de WhatsApp) não recebe o caso."""
    import httpx

    from app.agent_bridge import AgentRunIdentityError

    recebidos: list[tuple[str, bytes]] = []

    def impostor(request: httpx.Request) -> httpx.Response:
        recebidos.append((request.url.path, request.content))
        return httpx.Response(404, text="Cannot POST")

    config = AgentRunClientConfig(base_url="http://127.0.0.1:3000", principal=PRINCIPAL, project=PROJECT, secret=SECRET)
    with pytest.raises(AgentRunIdentityError):
        AgentRunClient(config, transport=httpx.MockTransport(impostor)).run(_request(config))
    assert [path for path, _ in recebidos] == ["/v1/agent-runs/identity"]
    assert set(json.loads(recebidos[0][1]).keys()) == {"challenge"}  # só o desafio saiu, nenhum dado de caso


def test_impostor_que_imita_o_protocolo_mas_nao_tem_o_segredo_e_barrado():
    import httpx

    from app.agent_bridge import AgentRunIdentityError

    def falsario(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"X-SAL-Protocol": "sal.agent-run/1.0",
                                            "X-SAL-Response-Signature": "f" * 64},
                              json={"protocol_version": "sal.agent-run/1.0", "service": "ai-orchestrator", "proof": "x"})

    config = AgentRunClientConfig(base_url="http://127.0.0.1:3100", principal=PRINCIPAL, project=PROJECT, secret=SECRET)
    with pytest.raises(AgentRunIdentityError):
        AgentRunClient(config, transport=httpx.MockTransport(falsario)).verify_identity()


def test_resposta_de_sucesso_sem_assinatura_ou_forjada_e_descartada(client):
    from app.agent_bridge import AgentRunIdentityError

    agent_client, config = client
    agent_client.verify_identity()
    FakeOrchestrator.behaviour["skip_signature"] = True
    with pytest.raises(AgentRunIdentityError):
        agent_client.run(_request(config))
    FakeOrchestrator.behaviour.clear()
    FakeOrchestrator.behaviour["forge_signature"] = True
    with pytest.raises(AgentRunIdentityError):
        agent_client.run(_request(config, case_id="caso-forjado"))


@pytest.mark.parametrize(
    "url",
    ["ftp://127.0.0.1:3100", "http://orchestrator.remoto:3100", "http://user:senha@127.0.0.1:3100",
     "http://127.0.0.1:3100/v1/agent-runs", "http://127.0.0.1:3100?x=1", "nao-e-url"],
)
def test_base_url_invalida_ou_insegura_e_recusada(url):
    with pytest.raises(ValueError):
        AgentRunClientConfig(base_url=url, principal=PRINCIPAL, project=PROJECT, secret=SECRET)


def test_base_url_valida():
    for url in ("http://127.0.0.1:3100", "http://localhost:3100/", "https://agente-i-a.vercel.app"):
        AgentRunClientConfig(base_url=url, principal=PRINCIPAL, project=PROJECT, secret=SECRET)


def test_falha_do_runner_mostra_o_motivo_real_e_nao_unknown():
    """Regressão da Fase 6: o 502 do primeiro caso real apareceu como 'unknown' no cliente."""
    from app.agent_bridge.client import _failure_reason

    runner_body = {
        "status": "failed_provider",
        "output_validation": {"valid": False, "reason": "HTTP 400 do provider"},
        "providers": {"primary": "anthropic", "primary_failure": "This operation was aborted",
                      "fallback_provider": "openai", "fallback_result": "error: HTTP 400 do provider"},
    }
    code, detail = _failure_reason(runner_body)
    assert code == "failed_provider"
    assert "aborted" in detail and "HTTP 400" in detail and "unknown" not in detail
    assert _failure_reason({"error": "permission_denied", "detail": "sem agent_run"}) == ("permission_denied", "sem agent_run")
