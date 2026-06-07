FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app (respects .dockerignore — no .env, no .venv, no .git).
COPY . .

EXPOSE 8000

# Same command as the Procfile. Production = BYOK only; do NOT bake
# OPENAI_API_KEY into the image or set it on a public host.
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
