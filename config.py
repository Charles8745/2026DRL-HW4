import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
MAX_TOOL_CALLS_PER_TURN = 6   # spec §8 per-turn cap


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# ALLOW_ENV_KEY: sole authorization for the .env (config.API_KEY) fallback.
# Default OFF. Even when ON it is only honored on localhost (or with an explicit
# public override) — see fe/keyauth.extract_request_key. DEMO_MODE is UI-only and
# does NOT authorize config.API_KEY.
ALLOW_ENV_KEY = _flag("ALLOW_ENV_KEY")
DEMO_MODE = _flag("DEMO_MODE")
