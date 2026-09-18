"""Assinatura SAL-HMAC-SHA256 do lado do SAL OS (mesma string canônica do Orchestrator).

Canônico: METHOD\\nPATH\\ntimestamp\\nnonce\\nprincipal\\nsha256(body em hex)
O segredo nunca é registrado, devolvido em mensagem de erro ou incluído em repr.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime

AUTH_SCHEME = "SAL-HMAC-SHA256"


def body_hash_hex(raw_body: str) -> str:
    return hashlib.sha256(raw_body.encode("utf-8")).hexdigest()


def canonical_string(*, method: str, path: str, timestamp: str, nonce: str, principal: str, body_hash: str) -> str:
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{principal}\n{body_hash}"


def sign(secret: str, canonical: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def authorization_header(
    *,
    secret: str,
    method: str,
    path: str,
    principal: str,
    raw_body: str,
    timestamp: datetime | None = None,
    nonce: str | None = None,
) -> str:
    stamp = (timestamp or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    value = nonce or uuid.uuid4().hex
    signature = sign(
        secret,
        canonical_string(
            method=method, path=path, timestamp=stamp, nonce=value, principal=principal,
            body_hash=body_hash_hex(raw_body),
        ),
    )
    return f"{AUTH_SCHEME} principal={principal},timestamp={stamp},nonce={value},signature={signature}"
