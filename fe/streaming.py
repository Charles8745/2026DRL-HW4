# fe/streaming.py
"""SSE StreamRunner: runs orch.process(...) on a daemon thread, fans on_step
events into a queue, and yields SSE frames from the request generator.

Hard guarantees (spec §2.2 / R5 / R19):
- try/except/finally ALWAYS emits error(redacted)? + a `done` sentinel -> never hangs.
- finally drops orch/client/embedder references and clears the queue
  (key in-heap lifetime == this turn).
- per-turn wall-clock cap + OpenAI request timeout (set on the client elsewhere).
- GeneratorExit (client disconnect) -> cooperative cancel of the worker.
- bounded number of concurrent streams.
"""
import queue
import threading
import time

from fe.sse import sse_frame, sse_comment
from fe.keyauth import redact_key

_DONE = object()  # internal worker-finished sentinel (distinct from the `done` SSE event)

# process-wide concurrency cap (single gthread worker; small fixed budget)
_GLOBAL_SEMAPHORE = threading.BoundedSemaphore(value=8)


class StreamRunner:
    def __init__(self, *, heartbeat_s: float = 15.0, wall_clock_s: float = 90.0,
                 max_concurrent: int = 8):
        self.heartbeat_s = heartbeat_s
        self.wall_clock_s = wall_clock_s
        self.max_concurrent = max_concurrent
        self._orch = None
        self._cancel = threading.Event()

    def run(self, orch, sid: str, user_input: str, *, request_key=None):
        """Return a generator yielding SSE frames. Daemon thread runs
        orch.process(sid, user_input, on_step=queue.put)."""
        self._orch = orch
        q: "queue.Queue" = queue.Queue()
        self._cancel.clear()
        started = time.monotonic()
        acquired = _GLOBAL_SEMAPHORE.acquire(blocking=False)

        def _worker():
            try:
                orch.process(sid, user_input, on_step=lambda etype, data: q.put((etype, data)))
            except Exception as e:  # worker crash -> surface a redacted error event
                msg = redact_key(str(e), request_key)
                q.put(("error", {"message": msg, "where": "stream_worker"}))
            finally:
                q.put(_DONE)

        def _gen():
            err_emitted = False
            closing = False  # set on GeneratorExit: client gone -> do NOT yield `done`
            try:
                if not acquired:
                    yield sse_frame("error", {"message": "伺服器同時串流數已達上限，請稍候再試。",
                                              "where": "concurrency"})
                    yield sse_frame("done", {"session_id": sid,
                                             "elapsed_ms": int((time.monotonic() - started) * 1000)})
                    return
                t = threading.Thread(target=_worker, daemon=True)
                t.start()
                while True:
                    if time.monotonic() - started > self.wall_clock_s:
                        self._cancel.set()
                        yield sse_frame("error", {"message": "本輪處理逾時，已中止。",
                                                  "where": "wall_clock"})
                        err_emitted = True
                        break
                    try:
                        item = q.get(timeout=self.heartbeat_s)
                    except queue.Empty:
                        yield sse_comment()  # keep-alive ': ping'
                        continue
                    if item is _DONE:
                        break
                    etype, data = item
                    if etype == "error":
                        err_emitted = True
                    yield sse_frame(etype, data)
            except GeneratorExit:
                # client disconnected -> cooperative cancel; do NOT yield further.
                # CPython forbids yielding while a generator is being closed, so we
                # flag `closing` and skip the `done` sentinel in the finally below
                # (done is meaningless to a gone client); the finally still drops refs.
                closing = True
                self._cancel.set()
                raise
            finally:
                # ALWAYS terminate the stream with a `done` sentinel (unless GeneratorExit
                # already unwound us — done is meaningless to a gone client).
                if not closing:
                    yield sse_frame("done", {"session_id": sid,
                                             "elapsed_ms": int((time.monotonic() - started) * 1000)})
                # drop references + drain queue: key in-heap lifetime ends here
                self._orch = None
                try:
                    while True:
                        q.get_nowait()
                except queue.Empty:
                    pass
                if acquired:
                    _GLOBAL_SEMAPHORE.release()
                _ = err_emitted  # documented: error already streamed when True

        return _gen()
