"""NotificationService — camada abstrata de canais.

Canais internos (sempre): terminal, outbox (arquivo .md no state dir).
Canal externo (só com notification.external_enabled=true — decisão da Tatiana):
  email_agent  → Email Agent oficial SAL (C:\\CENTRO-DE-AGENTES-IA\\agents\\email_agent.py)
Nenhum SMTP/Resend próprio e nenhum segundo sistema de mensagens (regra do ecossistema:
notificação pertence ao Email Agent). Ver docs/alignment-sal-os.md.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from .models import now_local
from .redact import redact


@dataclass
class Notification:
    kind: str  # immediate | daily_report | digest
    subject: str
    body: str
    priority: str = "P2"
    incident_id: str | None = None
    dedupe_key: str = ""
    tag: str = "ALERTA"  # tag do Email Agent


class Channel(Protocol):
    name: str
    external: bool

    def send(self, note: Notification) -> tuple[bool, str]: ...


class TerminalChannel:
    name, external = "terminal", False

    def send(self, note: Notification) -> tuple[bool, str]:
        print(f"\n===== {note.subject} =====\n{note.body}\n", flush=True)
        return True, "stdout"


class OutboxChannel:
    name, external = "outbox", False

    def __init__(self, directory: Path):
        self.directory = directory

    def send(self, note: Notification) -> tuple[bool, str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = now_local().strftime("%Y%m%d-%H%M%S")
        slug = (note.incident_id or note.kind).replace(":", "-")
        path = self.directory / f"{stamp}-{note.kind}-{slug}.md"
        path.write_text(f"# {note.subject}\n\n```text\n{note.body}\n```\n", encoding="utf-8")
        return True, str(path)


class EmailAgentChannel:
    name, external = "email_agent", True

    def __init__(self, path: str, recipient: str):
        self.path, self.recipient = path, recipient

    def send(self, note: Notification) -> tuple[bool, str]:
        if self.path not in sys.path:
            sys.path.insert(0, self.path)
        try:
            from agents.email_agent import enviar_email  # type: ignore[import-not-found]
        except ImportError as exc:
            return False, f"Email Agent indisponível: {exc}"
        response = enviar_email(destinatario=self.recipient, tag=note.tag, assunto=note.subject, corpo=note.body,
                                corpo_html=False)
        return True, redact(str(response))[:300]


class NotificationService:
    def __init__(self, settings, store, channels: list[Any] | None = None):
        self.settings = settings
        self.store = store
        self.cfg = settings["notification"]
        self.channels = channels if channels is not None else self._build()

    def _build(self) -> list[Any]:
        chosen = set(self.cfg.get("channels", []))
        channels: list[Any] = [OutboxChannel(self.settings.state_dir / "outbox")]
        if "terminal" in chosen:
            channels.append(TerminalChannel())
        email = self.cfg.get("email_agent") or {}
        if "email_agent" in chosen and email.get("recipient"):
            channels.append(EmailAgentChannel(email["path"], email["recipient"]))
        return channels

    def notify(self, note: Notification) -> dict[str, str]:
        note.body, note.subject = redact(note.body), redact(note.subject)
        key = note.dedupe_key or f"{note.kind}:{note.incident_id}"
        if self.store.notified_recently(key, float(self.cfg.get("dedupe_hours", 12))):
            return {"status": "DEDUPED"}
        external_allowed = bool(self.cfg.get("external_enabled"))
        per_hour = int(self.settings["rate_limits"]["notifications_per_hour"])
        if external_allowed and note.kind != "daily_report":
            if self.store.count_notifications(now_local() - timedelta(hours=1)) >= per_hour:
                external_allowed = False
        results: dict[str, str] = {}
        for channel in self.channels:
            if channel.external and not external_allowed:
                results[channel.name] = "SKIPPED (externo desabilitado ou rate limit)"
                continue
            try:
                ok, detail = channel.send(note)
            except Exception as exc:  # canal quebrado não derruba o ciclo
                ok, detail = False, f"{type(exc).__name__}: {redact(str(exc))[:200]}"
            self.store.record_notification(channel.name, note.kind, note.incident_id, key, ok, note.body)
            results[channel.name] = ("OK " if ok else "FALHA ") + detail
        return results
