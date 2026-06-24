# ═══════════════════════════════════════════════════════════════════
# IvyeaOps Dockerfile — with IvyeaAgent built-in
# ═══════════════════════════════════════════════════════════════════

# ── Stage 1: Frontend build ────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY client/package.json client/package-lock.json ./
RUN npm ci --ignore-scripts
COPY client/ ./
RUN npm run build

# ── Stage 2: Runtime ───────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx curl procps git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies for IvyeaOps
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Built-in IvyeaAgent runtime (Agent + knowledge base + local retrieval).
ARG IVYEA_AGENT_REPO=https://github.com/Hector-xue/ivyea-agent.git
ARG IVYEA_AGENT_REF=main
RUN pip install --no-cache-dir "git+${IVYEA_AGENT_REPO}@${IVYEA_AGENT_REF}"

# Copy backend source
COPY server/ ./server/

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist /app/client/dist

# Copy nginx config
COPY deploy/docker/nginx.conf /etc/nginx/nginx.conf

# Default environment
ENV IVYEA_OPS_DATA_DIR=/app/data
ENV IVYEA_OPS_HOST=0.0.0.0
ENV IVYEA_OPS_PORT=8001
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/server
ENV HOME=/root
ENV IVYEA_HOME=/root/.ivyea

# Create data directory
RUN mkdir -p /app/data /root/.ivyea/knowledge /root/.ivyea/models

# Expose ports
EXPOSE 80

# Entrypoint script
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
