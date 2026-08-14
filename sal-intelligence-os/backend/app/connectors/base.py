"""Interface de conector — docs/ARCHITECTURE.md item 1 (Data Connectors).

Objetivo: trocar mock por fonte real sem alterar Detection Engine / agentes.
Cada método devolve dicts simples (serializáveis), nunca objetos ORM — para não vazar
detalhe de implementação de uma fonte específica para quem consome.
"""

from abc import ABC, abstractmethod


class DreConnector(ABC):
    """Fonte de DRE/orçamento. Fase 0/1: só existe implementação mock (docs/DATA_MODEL.md#MetricDefinition
    não tem, hoje, fonte real mapeada — ver riscos da apresentação da Fase 0)."""

    @abstractmethod
    def get_dre(self, period: str) -> dict:
        """Retorna a DRE orçado x realizado do período (mesma forma de examples/dre_margin_case.md)."""

    @abstractmethod
    def get_concentration(self, period: str) -> dict:
        """Retorna a decomposição de concentração (linha, cliente, região, vendedor, fornecedor, rota)."""


class OperationalConnector(ABC):
    """Fonte de custos e entregas operacionais (coleta/transferência/entrega)."""

    @abstractmethod
    def get_cost_by_branch(self, period: str) -> list[dict]:
        """Custo consolidado por filial no período."""

    @abstractmethod
    def get_freight_by_route(self, period: str) -> list[dict]:
        """Frete/faturamento por rota (UF origem -> UF destino) no período."""

    @abstractmethod
    def get_delivery_delay(self, period: str) -> list[dict]:
        """Atraso de entrega por filial/rota no período."""
