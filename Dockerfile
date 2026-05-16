# SUGA 単一コンテナ用 Dockerfile（フロント同梱・1ポート）。
# 社内サーバや常時起動PCで動かす場合に使用する。
#   docker compose up -d  →  http://<ホストIP>:8000

# --- Stage 1: フロントエンドをビルド ---
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: バックエンド + フロント同梱 ---
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY backend/app ./app
COPY --from=frontend /fe/dist ./app/static

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
