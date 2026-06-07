import re

import os

import config

# Generic OpenAI-shaped key matcher used for redaction (sk- + >=20 url-safe chars).
_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
_REDACTED = "sk-***REDACTED***"


def validate_key_format(key: "str | None") -> bool:
    """UX precheck ONLY (not a security control): ^sk- prefix, len >= 20, no whitespace."""
    if not key:
        return False
    if any(ch.isspace() for ch in key):
        return False
    return key.startswith("sk-") and len(key) >= 20


def redact_key(text: str, key: "str | None") -> str:
    """Replace the literal key (if given) AND any generic sk-[A-Za-z0-9_-]{20,}
    run with 'sk-***REDACTED***'. Idempotent and safe on non-string-free text."""
    if not isinstance(text, str):
        text = str(text)
    if key:
        text = text.replace(key, _REDACTED)
    return _KEY_RE.sub(_REDACTED, text)


_LOCALHOST = {"127.0.0.1", "::1", "localhost"}


def _is_localhost(req) -> bool:
    addr = getattr(req, "remote_addr", None) or ""
    return addr in _LOCALHOST


def extract_request_key(req, *, allow_env: bool) -> "str | None":
    """Header 'X-RideButler-Key' ONLY. If allow_env, fall back to config.API_KEY,
    but the .env fallback is honored only on localhost (or with an explicit
    ALLOW_ENV_KEY_PUBLIC=1 public override). Never read a body field."""
    header_key = req.headers.get("X-RideButler-Key")
    if header_key:
        return header_key
    if not allow_env:
        return None
    public_ok = os.getenv("ALLOW_ENV_KEY_PUBLIC", "0").strip().lower() in ("1", "true", "yes", "on")
    if not (public_ok or _is_localhost(req)):
        return None              # R1: do NOT leak owner key on a public host
    return config.API_KEY or None
