"""Guard: every LLM-Protocol duck-type used by eval must accept the streaming
`on_token` kwarg. The eval's ThrottledRetryClient wraps OpenAIClient; when the
Protocol gained on_token (M3 streaming), this wrapper had to forward it too —
otherwise eval breaks with `unexpected keyword argument 'on_token'` even though
the FakeLLM-based unit tests stay green. Offline signature check (no API key)."""
import inspect

from be.eval.run_full import ThrottledRetryClient


def test_throttle_client_generate_accepts_on_token():
    params = inspect.signature(ThrottledRetryClient.generate).parameters
    assert "on_token" in params, "ThrottledRetryClient.generate must forward on_token (LLM Protocol)"
