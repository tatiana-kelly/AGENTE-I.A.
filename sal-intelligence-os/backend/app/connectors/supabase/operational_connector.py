"""Conector real de dados operacionais — projeto Supabase `relatorios-raw`.

Único conector "real" da Fase 1 (decisão da apresentação da Fase 0): DRE/orçamento continuam mock,
mas custo por filial, frete por rota e atraso de entrega já existem de verdade nesta base e são lidos
diretamente aqui, sem duplicar/mockar o que já está em produção.

Tabelas usadas (confirmadas via MCP Supabase em 2026-08-13, projeto fsswfealkyavtjfaleil):
- os_custos: custo/faturamento por ordem de serviço, com unidade e mês.
- relatorio_455_processado: frete por CT-e (filial, cliente, UF origem/destino, valor_frete).
- 455_consolidado_mes_atual: detalhe SSW por CTRC, inclui dias de atraso de entrega.
- mapa_filial: de-para inscrição de unidade -> nome de filial/empresa.

Credencial: string de conexão via variável de ambiente SUPABASE_RELATORIOS_RAW_URL
(postgresql://...). Nunca hardcoded — ver .claude/rules e MCP_INTEGRATION.md ("nunca expor
segredos no prompt"). Sem a env var configurada, os métodos levantam RuntimeError explicando
o que falta, em vez de silenciosamente devolver dado vazio ou inventado.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.connectors.base import OperationalConnector
from app.core.config import get_settings


class SupabaseOperationalConnector(OperationalConnector):
    def __init__(self, engine: Engine | None = None) -> None:
        if engine is not None:
            self._engine = engine
            return

        settings = get_settings()
        if not settings.supabase_relatorios_raw_url:
            self._engine = None
        else:
            self._engine = create_engine(settings.supabase_relatorios_raw_url)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError(
                "SUPABASE_RELATORIOS_RAW_URL não configurada. "
                "Defina a connection string do projeto relatorios-raw no .env (ver .env.example) "
                "antes de usar o SupabaseOperationalConnector."
            )
        return self._engine

    def get_cost_by_branch(self, period: str) -> list[dict]:
        query = text(
            """
            select
                unidade,
                count(*) as qtd_os,
                sum(faturamento) as faturamento_total,
                sum(valor_a_pagar) as custo_total,
                sum(faturamento) - sum(valor_a_pagar) as margem_bruta
            from os_custos
            where to_char(mes, 'YYYY-MM') = :period
            group by unidade
            order by custo_total desc nulls last
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"period": period}).mappings().all()
        return [dict(row) for row in rows]

    def get_freight_by_route(self, period: str) -> list[dict]:
        query = text(
            """
            select
                uf_origem,
                uf_destino,
                filial,
                count(*) as qtd_ctrc,
                sum(valor_frete) as valor_frete_total,
                sum(valor_icms) as icms_total
            from relatorio_455_processado
            where mes_referencia = :period
            group by uf_origem, uf_destino, filial
            order by valor_frete_total desc nulls last
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"period": period}).mappings().all()
        return [dict(row) for row in rows]

    def get_delivery_delay(self, period: str) -> list[dict]:
        query = text(
            """
            select
                unidade_emissora,
                count(*) as qtd_entregas,
                avg(nullif(quantidade_de_dias_de_atraso, '')::numeric) as atraso_medio_dias
            from "455_consolidado_mes_atual"
            where mes_referencia = :period
              and data_da_entrega_realizada is not null
              and data_da_entrega_realizada <> ''
            group by unidade_emissora
            order by atraso_medio_dias desc nulls last
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"period": period}).mappings().all()
        return [dict(row) for row in rows]

    def get_branch_map(self) -> list[dict]:
        """Auxiliar: de-para inscrição de unidade -> filial/empresa (mapa_filial). Não faz parte da
        interface OperationalConnector porque é dimensão, não fato — usado para dar nome legível
        às chaves de unidade_emissora/unidade retornadas pelos outros métodos."""
        query = text("select inscricao_unidade, filial_padrao, empresa_padrao from mapa_filial")
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [dict(row) for row in rows]
