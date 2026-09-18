"""Base dos adaptadores read-only: saídas reais da Torre → AlertEnvelope.

Regras comuns (valem para todos os adaptadores):
- só leitura: arquivos são abertos com read_text; nada é escrito na origem;
- nenhuma heurística silenciosa: toda transformação vira texto em `transformations`;
- campo que o motor não fornece não é inventado: fica neutro e documentado, ou a fonte vira
  source_quality="insufficient" (o DataQualityGate do Router bloqueia);
- timestamps da Torre vêm sem fuso e são interpretados como horário de Brasília (UTC-3, sem horário de verão).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from app.decision_router.inputs import AlertEnvelope

BRT = timezone(timedelta(hours=-3), "BRT")
INSUFFICIENT = "insufficient"
NEUTRAL_SEVERITY = "medium"
# ordinal dos próprios níveis de prioridade da Torre (config_investigador/config_projecao.niveis)
PRIORITY_SEVERITY = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}
SEVERITY_NOT_PROVIDED = "severity não fornecida pelo motor: 'medium' neutro (não usado pelo Router)"


@dataclass(frozen=True)
class AdaptedAlert:
    alert_id: str
    source: str
    envelope: AlertEnvelope
    source_ref: str
    transformations: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedRecord:
    source: str
    record_ref: str
    reason: str


@dataclass(frozen=True)
class AdapterOutput:
    source: str
    source_file: str | None
    records_read: int
    alerts: tuple[AdaptedAlert, ...]
    skipped: tuple[SkippedRecord, ...] = ()
    notes: tuple[str, ...] = ()


class TorreDataReader:
    """Acesso somente leitura ao diretório data/ da Torre."""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)

    def exists(self, relative: str) -> bool:
        return (self.data_dir / relative).is_file()

    def read_json(self, relative: str) -> Any:
        return json.loads((self.data_dir / relative).read_text(encoding="utf-8"))

    def sha256(self, relative: str) -> str:
        return "sha256:" + hashlib.sha256((self.data_dir / relative).read_bytes()).hexdigest()

    def latest(self, directory: str, pattern: str = "*.json") -> str | None:
        folder = self.data_dir / directory
        if not folder.is_dir():
            return None
        names = sorted(path.name for path in folder.glob(pattern) if path.is_file())
        return f"{directory}/{names[-1]}" if names else None


class TorreAdapter(Protocol):
    name: str

    def adapt(self, reader: TorreDataReader, rules_version: str) -> AdapterOutput: ...


def parse_torre_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=BRT)


def pseudonymize(value: str) -> str:
    return "anon:" + hashlib.sha256(value.strip().upper().encode("utf-8")).hexdigest()[:12]


def missing_file_output(source: str, relative: str) -> AdapterOutput:
    return AdapterOutput(
        source=source, source_file=relative, records_read=0, alerts=(),
        notes=(f"arquivo não encontrado: {relative}",),
    )
