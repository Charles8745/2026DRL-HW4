# RideButler — Deployment

> **PRODUCTION = BYOK ONLY. NEVER set `OPENAI_API_KEY` on a public host.**
> Keys arrive per-request via the `X-RideButler-Key` header. An env key on a
> public bind turns RideButler into an open proxy that burns the owner's key
> for every anonymous visitor.

## Why single instance (no multi-worker, no serverless)

RideButler keeps real state in **process memory**:

- `SessionStore._sessions` (conversation + slot memory, ordinal references),
- `CorpusEmbeddingCache` (the embedded catalog vector index),
- live **SSE** connections.

Multiple workers (or serverless invocations) each hold a **divergent copy** —
sessions, tickets, and the index would each be computed independently and
ordinal references would break. Therefore: `workers=1` (hard-clamped in
`gunicorn.conf.py`, with a boot self-check that refuses `>1`) on a **single
instance**. Serverless is out.

## SSE-safe gunicorn

- `worker_class='gthread'` — **not** `sync` (buffers the whole response and
  kills streaming), **not** `gevent` (monkeypatches the OpenAI SDK socket).
- `threads` tunable via `GUNICORN_THREADS` (default 8); `workers` forced to 1.
- `timeout=120`, `graceful_timeout=30`, `keepalive=5`.
- Stream routes set `X-Accel-Buffering: no` / `Cache-Control: no-store` /
  `Connection: keep-alive`; the generator emits periodic `: ping` comments.
- Access logs carry **no request body and no key**; a process-level logging
  filter redacts any `sk-` shape from every log line.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `DEMO_MODE` | `0` | UI-only: skip the key modal, show a demo banner. Does NOT authorize the env key. |
| `ALLOW_ENV_KEY` | `0` | Sole authorization for the `.env`-key fallback. Localhost-only unless the override below is also `1`. |
| `ALLOW_ENV_KEY_PUBLIC` | `0` | Explicit override to allow the env-key fallback on a non-localhost bind. **Keep `0` in production.** |
| `OPENAI_API_KEY` | _(unset)_ | Local-dev convenience only; ignored unless `ALLOW_ENV_KEY=1` on a localhost bind. **Never set on a public host.** |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Chat model. |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | Embedding model. |
| `GUNICORN_THREADS` | `8` | Threads in the single worker. |
| `WEB_CONCURRENCY` | `1` | Read but **hard-clamped to 1**; `>1` is rejected at boot. |
| `PORT` | `8000` | Bind port. |

## Render (render.yaml)

1. Push this repo to GitHub.
2. In Render, create a **Blueprint** from `render.yaml` (single web service,
   `numInstances: 1`, Docker runtime, health check `/`).
3. Leave `DEMO_MODE`, `ALLOW_ENV_KEY`, `ALLOW_ENV_KEY_PUBLIC` at `0`. **Do not
   add `OPENAI_API_KEY`.**
4. Deploy. The app boots **without** a real key (BYOK); users paste their own
   key into the in-app modal.

> **Free-tier cold start:** Render free instances spin down when idle and take
> ~30–60s to wake on the next request. The first hit (and the first SSE turn
> after idle) will be slow; this is the platform, not the app. Use a paid
> instance or an external pinger if you need always-warm.

## Generic Docker

```bash
docker build -t ridebutler .
# BYOK: no key in the container. Map a port and run.
docker run --rm -p 8000:8000 -e DEMO_MODE=0 -e ALLOW_ENV_KEY=0 ridebutler
# Health check:
curl -fsS http://localhost:8000/ >/dev/null && echo "up"
```

## Local production-mode smoke

```bash
# Boot exactly as the Procfile does.
.venv/bin/gunicorn --config gunicorn.conf.py wsgi:app
# In another shell — SSE must stream incrementally (NOT one buffered burst):
curl -N -H "X-RideButler-Key: sk-yourkey" \
  -H "Content-Type: application/json" \
  -d '{"message":"3萬以內的速克達"}' \
  http://localhost:8000/api/chat/stream
```

`-N` disables curl buffering; you should see `event:`/`data:` frames arrive one
at a time with `: ping` heartbeats, not a single block at the end.

## Not supported

- **Serverless** (Lambda / Cloud Functions / Vercel functions): process memory
  resets per invocation — sessions, the vector index, and SSE all break.
- **Multi-worker / multi-instance**: state splits across copies. The config
  hard-clamps `workers=1` and refuses `>1` at boot.
