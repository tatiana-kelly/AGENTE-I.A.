"""Freios do modo autônomo: interruptor geral, interruptor por projeto, teto diário e teto por caso."""

from datetime import UTC, datetime

import pytest

from app.agent_bridge.autonomy import (
    DEFAULT_POLICY_PATH,
    AutonomyBlocked,
    AutonomyGate,
    AutonomyPolicy,
    DailyLedger,
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _gate(tmp_path, *, enabled=True, projects=None, clock=None):
    policy = AutonomyPolicy(enabled=enabled, daily_budget_usd=10.0, case_budget_usd=3.5,
                            projects=projects if projects is not None else {"torre-controle": True, "dre": False})
    return AutonomyGate(policy, DailyLedger(tmp_path / "ledger.json", clock or Clock(datetime(2026, 9, 19, 13, tzinfo=UTC))))


def test_politica_versionada_comeca_desligada_com_os_tetos_decididos():
    policy = AutonomyPolicy.load(DEFAULT_POLICY_PATH)
    assert policy.enabled is False  # ligar é a ativação, que exige aprovação
    assert (policy.daily_budget_usd, policy.case_budget_usd) == (10.0, 3.5)
    assert set(policy.projects) == {"torre-controle", "dre", "rota-people", "produtividade"}


def test_interruptor_geral_desligado_bloqueia(tmp_path):
    with pytest.raises(AutonomyBlocked, match="interruptor geral"):
        _gate(tmp_path, enabled=False).case_budget("torre-controle")


@pytest.mark.parametrize("project", ["dre", "projeto-desconhecido"])
def test_projeto_desligado_ou_nao_cadastrado_bloqueia(tmp_path, project):
    with pytest.raises(AutonomyBlocked, match=project):
        _gate(tmp_path).case_budget(project)


def test_orcamento_do_caso_nunca_passa_do_que_resta_no_dia(tmp_path):
    gate = _gate(tmp_path)
    assert gate.case_budget("torre-controle") == 3.5
    gate.record(project="torre-controle", case_id="c1", reserved_usd=3.5)
    gate.record(project="torre-controle", case_id="c2", reserved_usd=3.5)
    assert gate.case_budget("torre-controle") == pytest.approx(3.0)  # 10 − 7
    gate.record(project="torre-controle", case_id="c3", reserved_usd=3.0)
    with pytest.raises(AutonomyBlocked, match="teto diário"):
        gate.case_budget("torre-controle")


def test_dia_de_brasilia_zera_o_teto_e_preserva_o_historico(tmp_path):
    clock = Clock(datetime(2026, 9, 20, 2, 59, tzinfo=UTC))  # 23h59 de 19/09 em Brasília
    gate = _gate(tmp_path, clock=clock)
    gate.record(project="torre-controle", case_id="c1", reserved_usd=10.0)
    with pytest.raises(AutonomyBlocked):
        gate.case_budget("torre-controle")
    clock.now = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)  # 00h00 de 20/09 em Brasília
    assert gate.case_budget("torre-controle") == 3.5
    assert gate.ledger.spent("2026-09-19") == 10.0


def test_reserva_negativa_nao_devolve_orcamento(tmp_path):
    gate = _gate(tmp_path)
    gate.record(project="torre-controle", case_id="c1", reserved_usd=-5)
    assert gate.ledger.spent() == 0.0


def test_teto_por_caso_da_politica_nunca_passa_da_politica_do_codigo(tmp_path):
    path = tmp_path / "p.json"
    path.write_text('{"enabled": true, "daily_budget_usd": 10, "case_budget_usd": 50, "projects": {}}', encoding="utf-8")
    assert AutonomyPolicy.load(path).case_budget_usd == 3.5
