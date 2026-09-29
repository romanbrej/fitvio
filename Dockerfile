# Health Wall — one image for the dashboard (web) and the Garmin sync.
# Build: docker compose build      Run: docker compose up -d      (see docker-compose.yml)

# --- 1. frontend (React/Vite) -----------------------------------------------------------
# Debian-based on purpose: npm on Alpine/ARM (e.g. Raspberry Pi) can die with "Exit handler never called"
FROM node:22-bookworm-slim AS frontend
# Docker networks usually have no IPv6, but the npm registry resolves to IPv6 first → npm stalls and
# crashes. Prefer IPv4 during the build.
ENV NODE_OPTIONS=--dns-result-order=ipv4first
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund || (sleep 5 && npm ci --no-audit --no-fund)
COPY frontend/ ./
RUN npm run build

# --- 2. backend (Python) + built frontend ---------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp
# tzdata: timestamps are local time (Garmin start times, "fresh activity" on the wall), set TZ in compose
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/healthdash backend/healthdash
# editable install: the app finds config/ and data/ relative to its source (/app)
RUN pip install -e ./backend
COPY --from=frontend /src/frontend/dist frontend/dist
COPY config/users.example.json config/
EXPOSE 8765
CMD ["healthdash", "serve", "--host", "0.0.0.0", "--port", "8765"]
