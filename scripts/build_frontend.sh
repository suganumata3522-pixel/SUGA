#!/usr/bin/env bash
# フロントエンドをビルドし、FastAPI が配信できる場所 (backend/app/static) へ配置する。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/3] フロントエンドの依存をインストール..."
( cd frontend && npm install --silent )

echo "[2/3] フロントエンドをビルド..."
( cd frontend && npm run build )

echo "[3/3] backend/app/static へ配置..."
rm -rf backend/app/static
cp -r frontend/dist backend/app/static

echo "完了: backend/app/static にフロントエンドを配置しました"
