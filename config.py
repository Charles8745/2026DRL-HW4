import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
MAX_TOOL_CALLS_PER_TURN = 6   # spec §8 per-turn cap

# Per-request OpenAI SDK timeout (seconds). Default 45 — must stay < the
# StreamRunner wall-clock (90s) so an aborted turn releases the key promptly
# instead of the SDK default 600s keeping a zombie worker (and the BYOK key) alive.
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "45"))


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# ALLOW_ENV_KEY: sole authorization for the .env (config.API_KEY) fallback.
# Default OFF. Even when ON it is only honored on localhost (or with an explicit
# public override) — see fe/keyauth.extract_request_key. DEMO_MODE is UI-only and
# does NOT authorize config.API_KEY.
ALLOW_ENV_KEY = _flag("ALLOW_ENV_KEY")
DEMO_MODE = _flag("DEMO_MODE")

# By default the .env fallback is permitted only on a localhost bind. A public
# host (e.g. 0.0.0.0 / a routable IP) re-burns the owner's key for every
# anonymous visitor unless this explicit override is set.
ALLOW_ENV_KEY_PUBLIC = _flag("ALLOW_ENV_KEY_PUBLIC")

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


def _is_localhost(bind_host: str) -> bool:
    return (bind_host or "").strip().lower() in _LOCAL_HOSTS


def env_fallback_allowed(bind_host: str) -> bool:
    """Single decision point for whether config.API_KEY may back a request.
    Requires ALLOW_ENV_KEY, AND (localhost bind OR explicit public override)."""
    if not ALLOW_ENV_KEY:
        return False
    if _is_localhost(bind_host):
        return True
    return ALLOW_ENV_KEY_PUBLIC


def boot_flag_warnings(bind_host: str) -> list[str]:
    """Return human-readable WARNING strings for dangerous flag combos.
    NEVER includes the key literal. Caller is responsible for logging them."""
    warnings: list[str] = []
    if ALLOW_ENV_KEY and API_KEY and not _is_localhost(bind_host):
        warnings.append(
            "DANGEROUS: ALLOW_ENV_KEY=1 with a non-empty OPENAI_API_KEY on a "
            "public bind (%s). Every anonymous visitor will spend the owner's "
            "key. Set ALLOW_ENV_KEY=0 for public hosts (production = BYOK only)."
            % (bind_host or "<unset>")
        )
    return warnings
