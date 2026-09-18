"""Repositório Postgres/Supabase da memória do Router (schema decision_router, migration 001).

NÃO EXECUTADO contra banco real: não há projeto Supabase aprovado para o SAL OS (D4). Regras:
- só aceita URL postgresql:// (SQLite não é memória de produção);
- read_only=True (padrão) recusa qualquer escrita antes de abrir transação;
- idempotência pela constraint unique(exact_fingerprint) + ON CONFLICT DO NOTHING.
"""

import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.decision_router.memory.records import CaseRecord, PatternStatsRecord, PlaybookRecord
from app.decision_router.memory.repository import MemoryWriteBlocked

SCHEMA = "decision_router"
_JSON_FIELDS = {"hypotheses", "recommendation", "evidence", "route_payload", "conditions", "recommended_action"}
_ARRAY_FIELDS = {"approval_flags", "selected_agents"}

INSERT_CASE_SQL = (
    f"insert into {SCHEMA}.case_routes ({{columns}}) values ({{values}}) "
    "on conflict (exact_fingerprint) do nothing returning id"
)
UPSERT_STATS_SQL = (
    f"insert into {SCHEMA}.pattern_stats ({{columns}}) values ({{values}}) "
    "on conflict (pattern_key) do update set {updates}"
)


def validate_database_url(url: str) -> str:
    if not url.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://")):
        raise ValueError("memória do Decision Router exige Postgres/Supabase; SQLite e outros bancos são recusados")
    return url


def _params(record) -> dict:
    data = record.model_dump(mode="json")
    for key in _JSON_FIELDS & data.keys():
        data[key] = json.dumps(data[key], ensure_ascii=False) if data[key] is not None else None
    for key in _ARRAY_FIELDS & data.keys():
        data[key] = list(data[key])
    return data


def _row(model, mapping) -> object:
    data = dict(mapping)
    for key in _JSON_FIELDS & data.keys():
        if isinstance(data[key], str):
            data[key] = json.loads(data[key])
    return model.model_validate(data)


class PostgresCaseMemoryRepository:
    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None, read_only: bool = True) -> None:
        if engine is None:
            if database_url is None:
                raise ValueError("database_url ou engine obrigatório")
            engine = create_engine(validate_database_url(database_url), pool_pre_ping=True)
        elif engine.dialect.name != "postgresql":
            raise ValueError("memória do Decision Router exige Postgres/Supabase")
        self._engine = engine
        self.read_only = read_only

    def _guard(self, what: str) -> None:
        if self.read_only:
            raise MemoryWriteBlocked(f"SHADOW_READ_ONLY: {what} bloqueada")

    def record_case(self, case: CaseRecord) -> tuple[CaseRecord, bool]:
        existing = self.get_by_exact(case.exact_fingerprint)
        if existing is not None:
            return existing, False
        self._guard("gravação de caso")
        params = _params(case)
        sql = INSERT_CASE_SQL.format(columns=", ".join(params), values=", ".join(f":{key}" for key in params))
        with self._engine.begin() as connection:
            inserted = connection.execute(text(sql), params).first()
        if inserted is None:  # corrida: outro processo gravou o mesmo exact_fingerprint
            return self.get_by_exact(case.exact_fingerprint), False
        return case, True

    def _one(self, model, sql: str, **params):
        with self._engine.connect() as connection:
            row = connection.execute(text(sql), params).mappings().first()
        return _row(model, row) if row is not None else None

    def get_by_exact(self, exact_fingerprint: str) -> CaseRecord | None:
        return self._one(CaseRecord, f"select * from {SCHEMA}.case_routes where exact_fingerprint = :value",
                         value=exact_fingerprint)

    def list_by_pattern(self, pattern_key: str) -> list[CaseRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(f"select * from {SCHEMA}.case_routes where pattern_key = :value order by observed_at"),
                {"value": pattern_key},
            ).mappings().all()
        return [_row(CaseRecord, row) for row in rows]

    def latest_by_lineage(self, lineage_key: str, before):
        return self._one(
            CaseRecord,
            f"select * from {SCHEMA}.case_routes where lineage_key = :value and observed_at < :before "
            "order by observed_at desc limit 1",
            value=lineage_key, before=before,
        )

    def get_pattern_stats(self, pattern_key: str) -> PatternStatsRecord | None:
        return self._one(PatternStatsRecord, f"select * from {SCHEMA}.pattern_stats where pattern_key = :value",
                         value=pattern_key)

    def save_pattern_stats(self, stats: PatternStatsRecord) -> None:
        self._guard("gravação de estatística")
        params = _params(stats)
        updates = ", ".join(f"{key} = excluded.{key}" for key in params if key != "pattern_key")
        sql = UPSERT_STATS_SQL.format(columns=", ".join(params), values=", ".join(f":{key}" for key in params),
                                      updates=updates)
        with self._engine.begin() as connection:
            connection.execute(text(sql), params)

    def get_current_playbook(self, pattern_key: str) -> PlaybookRecord | None:
        return self._one(
            PlaybookRecord,
            f"select * from {SCHEMA}.playbooks where pattern_key = :value order by version desc limit 1",
            value=pattern_key,
        )

    def save_playbook(self, playbook: PlaybookRecord) -> None:
        self._guard("gravação de playbook")
        if playbook.status == "active" and (not playbook.approved_by or playbook.approved_at is None):
            raise MemoryWriteBlocked("playbook ativo exige aprovação humana registrada")
        params = _params(playbook)
        sql = (f"insert into {SCHEMA}.playbooks ({', '.join(params)}) "
               f"values ({', '.join(f':{key}' for key in params)})")
        with self._engine.begin() as connection:
            connection.execute(text(sql), params)
