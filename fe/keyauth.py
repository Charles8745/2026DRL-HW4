import re

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
