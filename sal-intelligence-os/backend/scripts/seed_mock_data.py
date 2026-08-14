"""Popula o Metric Registry com a métrica usada pelo caso DRE obrigatório. Rodar uma vez:
    cd backend && python -m scripts.seed_mock_data
"""

from app.db.session import SessionLocal, init_db
from app.schemas.metric_definition import MetricDefinitionCreate
from app.services.metric_registry import MetricRegistry


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        registry = MetricRegistry(db)
        metric = registry.register(
            MetricDefinitionCreate(
                name="margem-bruta",
                objective="Manter margem bruta saudável sem perder clientes estratégicos",
                formula="(receita_liquida - custos) / receita_liquida",
                source="mock:dre_connector",
                grain="mensal",
                owner="diretoria financeira",
                target=36.0,
                warning_threshold=33.0,
                critical_threshold=30.0,
                materiality_rule="desvio absoluto de EBITDA >= R$ 200.000/mês",
                update_frequency="mensal",
            )
        )
        print(f"MetricDefinition registrada: {metric.id} ({metric.name}, v{metric.version})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
