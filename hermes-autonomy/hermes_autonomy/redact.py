"""Redação automática de segredos em qualquer texto que vá para log, memória ou notificação."""
from __future__ import annotations

import re

_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|[a-z_]*token|[a-z_]*secret|password|passwd|senha|authorization|client_secret|access_key)"
    r"(\s*[:=]\s*)([\"']?)[^\s\"',;]+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}")
_STRONG = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),  # JWT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
_DSN = re.compile(r"(?i)(postgres(?:ql)?://[^:\s/]+:)[^@\s]+(@)")


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED]", text)
    out = _BEARER.sub(r"\1[REDACTED]", out)
    for pattern in _STRONG:
        out = pattern.sub("[REDACTED]", out)
    return _DSN.sub(r"\1[REDACTED]\2", out)


def looks_like_secret(text: str) -> bool:
    """Detecção conservadora para validar arquivos versionados (registry/config)."""
    if any(p.search(text) for p in _STRONG) or _DSN.search(text):
        return True
    literal = re.compile(
        r"(?i)(api[_-]?key|token|secret|password|senha)\"?\s*[:=]\s*\"(?!\{env:)[A-Za-z0-9_\-]{12,}\""
    )
    return bool(literal.search(text))
