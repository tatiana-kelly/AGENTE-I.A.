"""Persistência local (SQLite): memória de incidentes, ciclo de vida, auditoria, tentativas,
notificações, circuit breaker e Skills candidatas. Um arquivo, sem servidor, sem dependências."""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import TERMINAL_STATES, now_local
from .redact import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT, mode TEXT, dry_run INTEGER, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, automation_id TEXT, slot TEXT, status TEXT, incident_type TEXT,
  checked_at TEXT, validated_by TEXT, findings_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_checks_auto ON checks(automation_id, checked_at);
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  fingerprint TEXT UNIQUE,
  automation_id TEXT, slot TEXT, type TEXT, state TEXT, priority TEXT, outcome TEXT,
  cause_code TEXT, cause_key TEXT, probable_cause TEXT, confidence REAL,
  root_cause_id TEXT, is_root INTEGER DEFAULT 0,
  detected_at TEXT, updated_at TEXT, resolved_at TEXT,
  attempts INTEGER DEFAULT 0, resolution TEXT, human_action TEXT,
  recovery_seconds INTEGER, check_json TEXT, diagnosis_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_inc_auto ON incidents(automation_id, detected_at);
CREATE TABLE IF NOT EXISTS incident_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT, ts TEXT, from_state TEXT, to_state TEXT, agent TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS repair_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT, automation_id TEXT, attempt INTEGER, action TEXT,
  idempotency_key TEXT UNIQUE, dry_run INTEGER, started_at TEXT, finished_at TEXT,
  result TEXT, validation TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, agent TEXT, automation TEXT, incident TEXT, action TEXT, reason TEXT,
  tool TEXT, result TEXT, validation TEXT, risk_level TEXT, dry_run INTEGER
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, channel TEXT, kind TEXT, incident_id TEXT, dedupe_key TEXT, delivered INTEGER, body TEXT
);
CREATE TABLE IF NOT EXISTS circuit (
  automation_id TEXT PRIMARY KEY, state TEXT, opened_at TEXT, until TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS skill_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cause_code TEXT, action TEXT, automation_id TEXT, success_count INTEGER,
  first_seen TEXT, last_seen TEXT, status TEXT,
  UNIQUE(cause_code, action, automation_id)
);
"""


def _ts(dt: datetime | None = None) -> str:
    return (dt or now_local()).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.db.execute(sql, params)
        self.db.commit()
        return cur

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    # ---------------- runs / checks
    def start_run(self, mode: str, dry_run: bool) -> int:
        return self._exec(
            "INSERT INTO runs(started_at, mode, dry_run) VALUES (?,?,?)", (_ts(), mode, int(dry_run))
        ).lastrowid

    def finish_run(self, run_id: int, summary: dict[str, Any]) -> None:
        self._exec("UPDATE runs SET finished_at=?, summary_json=? WHERE id=?", (_ts(), json.dumps(summary), run_id))

    def record_check(self, run_id: int | None, result) -> None:
        self._exec(
            "INSERT INTO checks(run_id, automation_id, slot, status, incident_type, checked_at, validated_by, findings_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, result.automation_id, result.slot, result.status, result.incident_type,
             result.checked_at, result.validated_by(), json.dumps([redact(f) for f in result.findings])),
        )

    def latest_checks(self, since: datetime) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT c.* FROM checks c JOIN (SELECT automation_id, MAX(id) mid FROM checks WHERE checked_at>=?"
            " GROUP BY automation_id) m ON c.id=m.mid ORDER BY c.automation_id",
            (_ts(since),),
        )

    # ---------------- incidents
    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM incidents WHERE id=?", (incident_id,))
        return rows[0] if rows else None

    def find_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM incidents WHERE fingerprint=?", (fingerprint,))
        return rows[0] if rows else None

    def create_incident(self, fingerprint: str, automation_id: str, slot: str | None, type_: str,
                        check_json: str, is_root: bool = False) -> dict[str, Any]:
        stamp = now_local()
        incident_id = f"INC-{stamp:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        self._exec(
            "INSERT INTO incidents(id, fingerprint, automation_id, slot, type, state, detected_at, updated_at,"
            " check_json, is_root) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (incident_id, fingerprint, automation_id, slot, type_, "DETECTED", _ts(stamp), _ts(stamp),
             redact(check_json), int(is_root)),
        )
        self._exec(
            "INSERT INTO incident_events(incident_id, ts, from_state, to_state, agent, note) VALUES (?,?,?,?,?,?)",
            (incident_id, _ts(stamp), None, "DETECTED", "hermes-guardian", type_),
        )
        return self.get_incident(incident_id)  # type: ignore[return-value]

    def transition(self, incident_id: str, to_state: str, agent: str, note: str = "") -> None:
        current = self.get_incident(incident_id)
        from_state = current["state"] if current else None
        stamp = _ts()
        self._exec("UPDATE incidents SET state=?, updated_at=? WHERE id=?", (to_state, stamp, incident_id))
        self._exec(
            "INSERT INTO incident_events(incident_id, ts, from_state, to_state, agent, note) VALUES (?,?,?,?,?,?)",
            (incident_id, stamp, from_state, to_state, agent, redact(note)),
        )

    def update_incident(self, incident_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _ts()
        cols = ", ".join(f"{k}=?" for k in fields)
        values = tuple(redact(v) if isinstance(v, str) and k in ("resolution", "human_action", "probable_cause",
                                                                   "diagnosis_json", "check_json") else v
                       for k, v in fields.items())
        self._exec(f"UPDATE incidents SET {cols} WHERE id=?", values + (incident_id,))

    def events(self, incident_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM incident_events WHERE incident_id=? ORDER BY id", (incident_id,))

    def open_incidents(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        return self._rows(
            f"SELECT * FROM incidents WHERE state NOT IN ({placeholders}) ORDER BY detected_at",
            tuple(TERMINAL_STATES),
        )

    def incidents(self, automation_id: str | None = None, cause_code: str | None = None,
                  since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM incidents WHERE 1=1", []
        if automation_id:
            sql += " AND automation_id=?"
            params.append(automation_id)
        if cause_code:
            sql += " AND cause_code=?"
            params.append(cause_code)
        if since:
            sql += " AND detected_at>=?"
            params.append(_ts(since))
        sql += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, tuple(params))

    def history(self, automation_id: str, cause_code: str | None = None,
                exclude_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.incidents(automation_id=automation_id, cause_code=cause_code, limit=200)
        return [r for r in rows if r["id"] != exclude_id and not r["is_root"]]

    def last_resolution(self, automation_id: str | None, cause_code: str) -> dict[str, Any] | None:
        sql = ("SELECT * FROM incidents WHERE cause_code=? AND state='RESOLVED' AND resolution IS NOT NULL")
        params: list[Any] = [cause_code]
        if automation_id:
            sql += " AND automation_id=?"
            params.append(automation_id)
        rows = self._rows(sql + " ORDER BY resolved_at DESC LIMIT 1", tuple(params))
        return rows[0] if rows else None

    # ---------------- repair attempts
    def begin_attempt(self, incident_id: str, automation_id: str, attempt: int, action: str,
                      dry_run: bool) -> int | None:
        key = f"{incident_id}:{attempt}:{action}"
        try:
            return self._exec(
                "INSERT INTO repair_attempts(incident_id, automation_id, attempt, action, idempotency_key, dry_run,"
                " started_at) VALUES (?,?,?,?,?,?,?)",
                (incident_id, automation_id, attempt, action, key, int(dry_run), _ts()),
            ).lastrowid
        except sqlite3.IntegrityError:
            return None  # mesma tentativa já registrada: não repetir

    def finish_attempt(self, attempt_id: int, result: str, validation: str) -> None:
        self._exec("UPDATE repair_attempts SET finished_at=?, result=?, validation=? WHERE id=?",
                   (_ts(), result, redact(validation), attempt_id))

    def attempts_for(self, incident_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM repair_attempts WHERE incident_id=? ORDER BY id", (incident_id,))

    def count_attempts(self, since: datetime, automation_id: str | None = None,
                       live_only: bool = True) -> int:
        sql, params = "SELECT COUNT(*) FROM repair_attempts WHERE started_at>=?", [_ts(since)]
        if automation_id:
            sql += " AND automation_id=?"
            params.append(automation_id)
        if live_only:
            sql += " AND dry_run=0"
        return int(self.db.execute(sql, tuple(params)).fetchone()[0])

    def count_failures(self, automation_id: str, since: datetime) -> int:
        """Falhas recentes: incidentes detectados + tentativas de reparo que não resolveram."""
        inc = self.db.execute(
            "SELECT COUNT(*) FROM incidents WHERE automation_id=? AND detected_at>=? AND is_root=0",
            (automation_id, _ts(since))).fetchone()[0]
        rep = self.db.execute(
            "SELECT COUNT(*) FROM repair_attempts WHERE automation_id=? AND started_at>=? AND dry_run=0"
            " AND result NOT IN ('SUCCESS','ALREADY_OK')",
            (automation_id, _ts(since))).fetchone()[0]
        return int(inc) + int(rep)

    # ---------------- audit
    def audit(self, agent: str, action: str, reason: str, result: str, *, automation: str | None = None,
              incident: str | None = None, tool: str = "", validation: str = "", risk_level: str = "low",
              dry_run: bool = True) -> None:
        self._exec(
            "INSERT INTO audit_log(ts, agent, automation, incident, action, reason, tool, result, validation,"
            " risk_level, dry_run) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_ts(), agent, automation, incident, action, redact(reason), tool, redact(result),
             redact(validation), risk_level, int(dry_run)),
        )

    def audit_entries(self, since: datetime | None = None, incident: str | None = None,
                      limit: int = 200) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM audit_log WHERE 1=1", []
        if since:
            sql += " AND ts>=?"
            params.append(_ts(since))
        if incident:
            sql += " AND incident=?"
            params.append(incident)
        return self._rows(sql + " ORDER BY id DESC LIMIT ?", tuple(params + [limit]))

    # ---------------- notifications
    def notified_recently(self, dedupe_key: str, hours: float) -> bool:
        since = now_local() - timedelta(hours=hours)
        row = self.db.execute("SELECT 1 FROM notifications WHERE dedupe_key=? AND ts>=? LIMIT 1",
                              (dedupe_key, _ts(since))).fetchone()
        return row is not None

    def record_notification(self, channel: str, kind: str, incident_id: str | None, dedupe_key: str,
                            delivered: bool, body: str) -> None:
        self._exec(
            "INSERT INTO notifications(ts, channel, kind, incident_id, dedupe_key, delivered, body)"
            " VALUES (?,?,?,?,?,?,?)",
            (_ts(), channel, kind, incident_id, dedupe_key, int(delivered), redact(body)),
        )

    def count_notifications(self, since: datetime, external_only: bool = True) -> int:
        sql = "SELECT COUNT(DISTINCT dedupe_key) FROM notifications WHERE ts>=?"
        if external_only:
            sql += " AND channel NOT IN ('terminal','outbox')"
        return int(self.db.execute(sql, (_ts(since),)).fetchone()[0])

    # ---------------- circuit breaker
    def get_circuit(self, automation_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM circuit WHERE automation_id=?", (automation_id,))
        return rows[0] if rows else None

    def set_circuit(self, automation_id: str, state: str, reason: str, until: datetime | None) -> None:
        self._exec(
            "INSERT INTO circuit(automation_id, state, opened_at, until, reason) VALUES (?,?,?,?,?)"
            " ON CONFLICT(automation_id) DO UPDATE SET state=excluded.state, opened_at=excluded.opened_at,"
            " until=excluded.until, reason=excluded.reason",
            (automation_id, state, _ts(), _ts(until) if until else None, reason),
        )

    # ---------------- skills candidatas
    def register_skill_candidate(self, cause_code: str, action: str, automation_id: str) -> dict[str, Any]:
        stamp = _ts()
        self._exec(
            "INSERT INTO skill_candidates(cause_code, action, automation_id, success_count, first_seen, last_seen,"
            " status) VALUES (?,?,?,1,?,?,'CANDIDATE') ON CONFLICT(cause_code, action, automation_id) DO UPDATE"
            " SET success_count=success_count+1, last_seen=excluded.last_seen",
            (cause_code, action, automation_id, stamp, stamp),
        )
        return self._rows("SELECT * FROM skill_candidates WHERE cause_code=? AND action=? AND automation_id=?",
                          (cause_code, action, automation_id))[0]

    def skill_candidates(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM skill_candidates ORDER BY success_count DESC")
