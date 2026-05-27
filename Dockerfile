# ═══════════════════════════════════════════════════════════════════
# ops-hub Dockerfile — with Hermes Agent built-in
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

# Install Hermes Agent
RUN git clone --depth 1 https://github.com/nousresearch/hermes-agent.git /opt/hermes-agent 2>/dev/null || \
    git clone --depth 1 https://github.com/Hector-xue/hermes-agent.git /opt/hermes-agent 2>/dev/null || true
RUN if [ -d /opt/hermes-agent ]; then \
        cd /opt/hermes-agent && \
        python3 -m venv venv && \
        . venv/bin/activate && \
        pip install --no-cache-dir -e . 2>/dev/null || true && \
        ln -sf /opt/hermes-agent/venv/bin/hermes /usr/local/bin/hermes; \
    fi

# Python dependencies for ops-hub
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Copy backend source
COPY server/ ./server/

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist /app/client/dist

# Copy nginx config
COPY deploy/docker/nginx.conf /etc/nginx/nginx.conf

# Default environment
ENV OPSHUB_DATA_DIR=/app/data
ENV OPSHUB_HOST=0.0.0.0
ENV OPSHUB_PORT=8001
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/server
ENV HOME=/root

# Create data directory
RUN mkdir -p /app/data /root/.hermes

# Expose ports
EXPOSE 80

# Entrypoint script
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
