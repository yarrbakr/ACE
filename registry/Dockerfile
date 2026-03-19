# ── Build stage ────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/
COPY registry/ registry/

RUN pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ──────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /install /usr/local
COPY registry/ registry/

# Create data directory for SQLite
RUN mkdir -p /data

ENV ACE_REGISTRY_DB=/data/registry.db
ENV PORT=9000

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"

CMD ["python", "-m", "registry"]
