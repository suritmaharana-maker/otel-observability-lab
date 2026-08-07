FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY llm_svc.py .
# Real Dash0 CLI binary, for genuine log-CONTENT queries (Tier 1 - actual
# audit-trail text, not a metric-count proxy). ghcr.io/dash0hq/cli:latest
# is FROM scratch with no CA cert bundle at all - it cannot verify Dash0's
# own TLS certificate. python:3.13-slim has a real, working cert store
# (confirmed - it's what every other outbound HTTPS call from this image
# already uses), so running the binary from here fixes that without any
# extra cert plumbing. Pulled directly from the registry at build time
# (not committed to this repo - it's a 23.8MB binary, and this keeps the
# build reproducible without needing a local file that would go stale).
COPY --from=ghcr.io/dash0hq/cli:latest /dash0 /usr/local/bin/dash0
RUN chmod +x /usr/local/bin/dash0
EXPOSE 8002
CMD ["uvicorn", "llm_svc:app", "--host", "0.0.0.0", "--port", "8002"]
