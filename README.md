# SUGA — 構造図 / 計算書 整合チェックツール

ゼネコン社内向け、RCマンションの **構造図PDF** と **一貫構造計算ソフト（StructureSuite ほか）の計算書PDF** の
整合性を自動チェックするためのWebアプリ。

## 適用範囲（Phase 1）

**RC 小梁（二次部材）** をターゲットとする。
柱・大梁ではないので注意。比較対象は以下:

- 符号 (例: B1, B1A, CG1, WCB2B)
- 断面 B (構造図側に D の数値テキストが無いため B のみ比較)
- 上端筋・下端筋・STP（あばら筋）・腹筋
- コンクリート強度（計算書側の Fc + 図面のコード番号）

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
| PDF解析 | pdfplumber (ベクター PDF の座標ベース抽出) |
| 永続化 | SQLite + SQLModel |
| 配布 | Docker Compose（社内イントラサーバへ設置）|

## ディレクトリ構成

```
backend/
  app/
    main.py            FastAPI エントリ
    models.py          共通データモデル（BeamMember, PositionRebar, Section）
    checker.py         整合チェッカー
    parsers/
      calc_pdf.py      StructureSuite 小梁計算書PDFパーサ
      drawing_pdf.py   二次部材リスト（小梁）PDFパーサ
    db.py              SQLModel/SQLite
  scripts/
    parse_samples.py   CLI でパース結果と差分を確認
  tests/
    test_checker.py
frontend/
  src/
    App.tsx            アップロード＋差分表示
    api.ts             バックエンドAPIクライアント
docker-compose.yml
```

## 社内への展開方法

本アプリは「FastAPI が React 画面も同時に配信する 1 プロセス・1 ポート」構成。
用途に応じて 2 通りの配り方ができる。

### 方法1: 各自の PC で個別に起動（推奨・最も手軽）

実行ファイル `SUGA.exe` を 1 つ配るだけ。利用者は Python も Docker も不要。

1. **ビルド担当者が一度だけ** `SUGA.exe` を作る（Windows / Python 3.11+ / Node.js 20+ が必要）
   ```
   scripts\build_exe.bat
   ```
   → `backend\dist\SUGA.exe` が生成される
2. その `SUGA.exe` を各利用者へ配布（社内共有フォルダ等）
3. 利用者は `SUGA.exe` をダブルクリック → 自動でブラウザが開く
   - データ（案件・PDF）は exe と同じ場所の `SUGA-data/` に保存される
   - 終了するときはコンソールウィンドウを閉じる

### 方法2: 社内サーバ / 常時起動 PC に 1 台だけ設置（共有利用）

Docker のある環境なら 1 コマンド。利用者はブラウザだけ。

```bash
docker compose up -d --build
# 利用者は http://<そのPCのIP>:8000 にアクセス
```

## 開発時の起動

```bash
# バックエンド（API + 同梱フロント配信）
cd backend && pip install -e ".[dev]" && python run.py

# フロントを編集しながら開発する場合は vite dev サーバを併用
cd frontend && npm install
VITE_API_BASE=http://localhost:8000 npm run dev   # http://localhost:5173
```

フロントを更新したら `scripts/build_frontend.sh` で `backend/app/static/` に反映する。

## CLI で動作確認

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m scripts.parse_samples <構造図PDF> <計算書PDF>
```

## 開発フロー

### Phase 1 — MVP（実装中）
- [x] プロジェクト骨組み（FastAPI / React / Docker / 共通モデル）
- [x] StructureSuite 計算書PDF パーサ（符号・B/D・主筋上下・STP・Fc を抽出）
- [x] 二次部材リスト（小梁）PDF パーサ（座標ベース）
- [x] 配筋・断面の突合と差分検出
- [ ] パーサ微調整（CG2A/CG7 のような左右配筋共有レイアウト）
- [ ] Fc コード ↔ 強度ラベル（凡例）対応表

### Phase 2
- [ ] SS7/SS3 計算書PDF 対応
- [ ] 計算書側の note（"1F 駐輪場" など）を UI に表示
- [ ] 元PDFハイライト表示（bbox は LocationHint に保持済み）

### Phase 3
- [ ] スラブ・壁リストへ対応拡張
- [ ] Excelレポート出力

## 共通データモデル

`backend/app/models.py` を参照。構造図側・計算書側のパーサは
すべて `BeamMember` に正規化して `checker.compare()` に渡す。

| フィールド | 内容 | 例 |
| --- | --- | --- |
| mark | 符号 | B1, B1A, CG1, WCB2B |
| section.B / D | 断面 (mm) | B=400, D=700 |
| positions[] | 位置ごとの配筋 | location="SX1端", top, bottom, stirrup, web |
| concrete_grade | コンクリート強度 | Fc36 |
| fc_code | 構造図上のコード | "006" |
| rebar_grade_main | 主筋鉄筋種 | SD345 |

## 差分検出例

サンプル `S4001 二次部材リスト + StructureSuite 小梁計算書` を流すと、
構造図と計算書で `CG1A` の STP（端部 #2端側）が `2-D13@200` vs `5-D13@200` で
食い違っていることが検出できる。
