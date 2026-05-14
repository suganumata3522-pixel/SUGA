# SUGA — 構造図 / 計算書 整合チェックツール

ゼネコン社内向け、RCマンションの **構造図PDF** と **一貫構造計算ソフト（SS7/SS3、StructureSuite）の計算書PDF** の
整合性を自動チェックするためのWebアプリ。

## 目的

- 部材リスト（柱・大梁・小梁・壁・スラブ）の符号一致
- 断面寸法・配筋・厚さの突合
- コンクリート強度（Fc）の整合
- 二次部材（小梁・スラブ）の照合まで段階的に拡張

## アーキテクチャ

```
┌──────────────────┐   PDFアップロード   ┌────────────────────────┐
│  React (Vite)    │ ─────────────────▶ │  FastAPI (Python)      │
│  ブラウザUI       │ ◀─────差分JSON─── │  パーサー＋チェッカー    │
└──────────────────┘                    └─────────┬──────────────┘
                                                  │
                                          SQLite (suga.db)
                                          /uploads/*.pdf
```

| レイヤ | 技術 |
| --- | --- |
| フロント | React + TypeScript + Vite |
| API | FastAPI (Python 3.12) |
| PDF解析 | pdfplumber / PyMuPDF |
| 永続化 | SQLite + SQLModel |
| 配布 | Docker Compose（社内イントラサーバへ設置）|

## ディレクトリ構成

```
backend/
  app/
    main.py            FastAPI エントリ
    models.py          共通データモデル（Member, Section, Rebar, ...）
    checker.py         整合チェッカー
    parsers/
      calc_pdf.py      SS7/SS3, StructureSuite 計算書PDF パーサー
      drawing_pdf.py   構造図PDFパーサー
    db.py              SQLModel/SQLite
  tests/
    test_checker.py
frontend/
  src/
    App.tsx            アップロード＋差分表示
    api.ts             バックエンドAPIクライアント
docker-compose.yml
```

## ローカル起動

```bash
docker compose up --build
# フロント: http://localhost:5173
# API:      http://localhost:8000/api/health
```

## 開発フロー

### Phase 1 — MVP（実装中）
- [x] プロジェクト骨組み（FastAPI / React / Docker / 共通モデル / チェッカー）
- [ ] SS7計算書PDFのサンプルから柱・大梁の部材リストを抽出
- [ ] 構造図PDF（ベクター）の部材リスト表抽出
- [ ] 符号・断面の突合

### Phase 2
- [ ] 主筋・帯筋・あばら筋の配筋照合
- [ ] StructureSuite対応

### Phase 3
- [ ] 小梁・壁・スラブ
- [ ] 元PDFハイライト表示
- [ ] Excelレポート出力

## バックエンド開発

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

## 共通データモデル

`backend/app/models.py` を参照。構造図側・計算書側のパーサーは
すべて `Member` に正規化して `checker.compare()` に渡す。

| フィールド | 内容 | 例 |
| --- | --- | --- |
| category | 部材分類 | 柱 / 大梁 / 小梁 / 壁 / スラブ |
| mark | 符号 | C1, G1, B1, W18, S15 |
| floor | 階 | 2F, RF |
| section.b / D | 断面寸法 (mm) | 800, 800 |
| section.thickness | 厚さ (mm) | 180 |
| rebar.main / hoop / ... | 配筋 | "12-D25", "4-D13@100" |
| concrete_grade | コンクリート強度 | Fc36 |
