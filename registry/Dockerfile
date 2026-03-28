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

# Create non-root user and data directory
RUN useradd -m -s /bin/bash ace && \
    mkdir -p /data /tmp && \
    chown -R ace:ace /data /tmp /app

USER ace

ENV ACE_REGISTRY_DB=/data/registry.db
ENV PORT=9000

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"

CMD ["python", "-m", "registry"]
