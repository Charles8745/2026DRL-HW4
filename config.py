import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_TOOL_CALLS_PER_TURN = 6   # spec §8 per-turn cap
