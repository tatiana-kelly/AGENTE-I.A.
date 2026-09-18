"""Cálculo de janelas esperadas (EXPECTED) a partir do agendamento declarado no registry.

Formatos de `schedule` aceitos:
  {"type": "daily", "times": ["06:00", "14:30"], "weekdays": "mon-fri"}   # weekdays opcional
  {"type": "interval", "every_minutes": 30, "anchor": "00:26", "window": ["00:00", "23:59"], "weekdays": "all"}
  {"type": "monthly", "day": 1, "time": "07:00"}
  {"type": "cron", "expr": "12 11,15 * * 1-5", "utc": true}
  {"type": "event"}                                                        # sem horário: só evento/manual
Horários são locais (máquina em America/Sao_Paulo), exceto cron com "utc": true.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

_WEEKDAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MAX_LOOKBACK_DAYS = 40


def parse_hhmm(value: str) -> time:
    hour, minute = value.strip().split(":")
    return time(int(hour), int(minute))


def parse_weekdays(spec: Any) -> set[int]:
    """Aceita 'all', 'mon-fri', 'mon,wed,fri' ou lista de inteiros (0=segunda)."""
    if spec in (None, "all", "*"):
        return set(range(7))
    if isinstance(spec, list):
        return {int(x) for x in spec}
    result: set[int] = set()
    for part in str(spec).lower().split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            a, b = _WEEKDAY_NAMES[start], _WEEKDAY_NAMES[end]
            result.update(range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1)))
        else:
            result.add(_WEEKDAY_NAMES[part])
    return result


def _cron_field(spec: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/")
            step = int(step_s)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-")
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return values


class CronExpr:
    def __init__(self, expr: str):
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError(f"cron inválido: {expr!r}")
        self.minutes = _cron_field(fields[0], 0, 59)
        self.hours = _cron_field(fields[1], 0, 23)
        self.dom = _cron_field(fields[2], 1, 31)
        self.months = _cron_field(fields[3], 1, 12)
        dow = _cron_field(fields[4], 0, 7)
        # cron: 0/7=domingo → python weekday: 6
        self.dow = {(d - 1) % 7 for d in dow}
        self.dom_restricted = fields[2] != "*"
        self.dow_restricted = fields[4] != "*"

    def matches_day(self, d: date) -> bool:
        if d.month not in self.months:
            return False
        dom_ok = d.day in self.dom
        dow_ok = d.weekday() in self.dow
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def times(self) -> list[time]:
        return [time(h, m) for h in sorted(self.hours) for m in sorted(self.minutes)]


def _day_slots(schedule: dict[str, Any], d: date, tz) -> list[datetime]:
    kind = schedule.get("type", "daily")
    if kind == "daily":
        if d.weekday() not in parse_weekdays(schedule.get("weekdays")):
            return []
        return [datetime.combine(d, parse_hhmm(t), tz) for t in schedule["times"]]
    if kind == "interval":
        if d.weekday() not in parse_weekdays(schedule.get("weekdays")):
            return []
        every = int(schedule["every_minutes"])
        anchor = parse_hhmm(schedule.get("anchor", "00:00"))
        window = schedule.get("window", ["00:00", "23:59"])
        w_start, w_end = parse_hhmm(window[0]), parse_hhmm(window[1])
        first = anchor.hour * 60 + anchor.minute
        first %= every
        slots = []
        for minute in range(first, 24 * 60, every):
            t = time(minute // 60, minute % 60)
            if w_start <= t <= w_end:
                slots.append(datetime.combine(d, t, tz))
        return slots
    if kind == "monthly":
        if d.day != int(schedule.get("day", 1)):
            return []
        return [datetime.combine(d, parse_hhmm(schedule["time"]), tz)]
    if kind == "cron":
        cron = CronExpr(schedule["expr"])
        if schedule.get("utc"):
            if not cron.matches_day(d):
                return []
            return [datetime.combine(d, t, timezone.utc).astimezone(tz) for t in cron.times()]
        if not cron.matches_day(d):
            return []
        return [datetime.combine(d, t, tz) for t in cron.times()]
    if kind in ("event", "none", "once"):
        return []
    raise ValueError(f"tipo de schedule desconhecido: {kind}")


def last_slot(schedule: dict[str, Any] | None, before: datetime) -> datetime | None:
    """Horário esperado mais recente <= before."""
    if not schedule:
        return None
    tz = before.tzinfo
    utc = schedule.get("type") == "cron" and schedule.get("utc")
    base = before.astimezone(timezone.utc).date() if utc else before.date()
    for offset in range(0, MAX_LOOKBACK_DAYS):
        d = base - timedelta(days=offset)
        candidates = [s for s in _day_slots(schedule, d, tz) if s <= before]
        if candidates:
            return max(candidates)
    return None


def slots_between(schedule: dict[str, Any] | None, start: datetime, end: datetime) -> list[datetime]:
    if not schedule:
        return []
    tz = end.tzinfo
    result: list[datetime] = []
    d = start.date() - timedelta(days=1)
    while d <= end.date() + timedelta(days=1):
        result.extend(s for s in _day_slots(schedule, d, tz) if start < s <= end)
        d += timedelta(days=1)
    return sorted(set(result))


def render_path(template: str, when: datetime, variables: dict[str, str] | None = None) -> str:
    """Substitui {date:%Y%m%d}, {var} e {env:NOME} no caminho."""
    import os
    import re

    def repl(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key.startswith("date:"):
            return when.strftime(key[5:])
        if key.startswith("env:"):
            return os.environ.get(key[4:], "")
        if variables and key in variables:
            return str(variables[key])
        return match.group(0)

    return re.sub(r"\{([^{}]+)\}", repl, template)
