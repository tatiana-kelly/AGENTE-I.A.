"""Audit Trail — docs/ARCHITECTURE.md item 13: fonte, timestamp, consulta, versão de regra, agente e decisão humana.

Fase 0: log append-only em arquivo JSONL local. Trocar o sink por uma tabela/Supabase quando o volume exigir
— mesma lição já registrada no PRP-003 (EvidenceManager com sink plugável), não recriar aqui.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class AuditEvent:
    timestamp: str
    event_type: str  # agent_call | tool_call | human_decision | data_access
    actor: str  # nome do agente, serviço ou usuário
    summary: str
    payload: dict = field(default_factory=dict)


class AuditTrail:
    def __init__(self, log_path: Path | str = "audit_trail.jsonl") -> None:
        self.log_path = Path(log_path)

    def record(self, event_type: str, actor: str, summary: str, payload: dict | None = None) -> AuditEvent:
        event = AuditEvent(
            timestamp=datetime.now(UTC).isoformat(),
            event_type=event_type,
            actor=actor,
            summary=summary,
            payload=payload or {},
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def read_all(self) -> list[AuditEvent]:
        if not self.log_path.exists():
            return []
        events = []
        with self.log_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(AuditEvent(**json.loads(line)))
        return events
