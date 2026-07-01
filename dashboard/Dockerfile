## Stage 1: Clone repo and build the React/Vite frontend
FROM node:22-slim AS frontend

ARG GIT_REF=standardize-audit

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /repo
RUN git clone --depth 1 --branch "${GIT_REF}" https://github.com/Empire-of-Shadows/Stygian-Relay.git .

WORKDIR /repo/dashboard/frontend
RUN npm install && npm run build


## Stage 2: Python backend serving FastAPI + built SPA
FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=frontend /repo /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r dashboard/requirements.txt

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 54013

CMD ["python", "-m", "dashboard.app"]
