from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .checker import Diff, compare, compare_slabs
from .config import STATIC_DIR
from .models import MemberSet, SlabSet
from .parsers import DrawingPdfParser, StructureSuitePdfParser, parse_calc_slabs, parse_drawing_slabs
from .pdf_render import render_highlight_png
from .report import build_report
from .storage import clear_all, delete_upload, find_path, list_uploads, role_paths, save_upload

app = FastAPI(title="SUGA - 構造図/計算書整合チェック", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# アップロード管理（案件の概念なし・構造図/計算書を複数ファイル保持）
# ---------------------------------------------------------------------------
@app.get("/api/uploads")
def get_uploads() -> dict:
    """現在アップロード済みのファイル一覧。"""
    items = list_uploads()
    return {
        "drawing": [i for i in items if i["role"] == "drawing"],
        "calc": [i for i in items if i["role"] == "calc"],
    }


@app.post("/api/uploads")
def upload(role: str = Form(...), files: list[UploadFile] = File(...)) -> list[dict]:
    """構造図PDF または 計算書PDF を1つ以上アップロードする。"""
    if role not in {"drawing", "calc"}:
        raise HTTPException(400, "role は 'drawing' か 'calc'")
    saved: list[dict] = []
    for f in files:
        data = f.file.read()
        if not data:
            continue
        saved.append(save_upload(role, f.filename or "file.pdf", data))
    if not saved:
        raise HTTPException(400, "ファイルが空です")
    return saved


@app.delete("/api/uploads/{file_id}")
def remove_upload(file_id: str) -> dict:
    if not delete_upload(file_id):
        raise HTTPException(404, "ファイルが見つかりません")
    return {"ok": True}


@app.post("/api/uploads/clear")
def clear_uploads() -> dict:
    clear_all()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 整合チェック（アップロード済みの全ファイルを結合して照合）
# ---------------------------------------------------------------------------
def _parse_drawings() -> tuple[MemberSet, SlabSet]:
    members = []
    slabs = []
    for fid, path in role_paths("drawing"):
        ms = DrawingPdfParser().parse(path)
        for m in ms.members:
            if m.location:
                m.location.file_id = fid
        members.extend(ms.members)
        ss = parse_drawing_slabs(path)
        for s in ss.slabs:
            if s.location:
                s.location.file_id = fid
        slabs.extend(ss.slabs)
    return (
        MemberSet(source="図", file_name="(構造図)", members=members),
        SlabSet(source="図", file_name="(構造図)", slabs=slabs),
    )


def _parse_calcs() -> tuple[MemberSet, SlabSet]:
    members = []
    slabs = []
    for fid, path in role_paths("calc"):
        ms = StructureSuitePdfParser().parse(path)
        for m in ms.members:
            if m.location:
                m.location.file_id = fid
        members.extend(ms.members)
        ss = parse_calc_slabs(path)
        for s in ss.slabs:
            if s.location:
                s.location.file_id = fid
        slabs.extend(ss.slabs)
    return (
        MemberSet(source="計算書", file_name="(計算書)", members=members),
        SlabSet(source="計算書", file_name="(計算書)", slabs=slabs),
    )


@app.post("/api/check")
def run_check() -> dict:
    if not role_paths("drawing") or not role_paths("calc"):
        raise HTTPException(400, "構造図PDFと計算書PDFを両方アップロードしてください")

    drawing_set, drawing_slabs = _parse_drawings()
    calc_set, calc_slabs = _parse_calcs()

    diffs: list[Diff] = compare(drawing_set, calc_set)
    slab_diffs: list[Diff] = compare_slabs(drawing_slabs, calc_slabs)

    def _mismatch_count(items: list[Diff]) -> int:
        return sum(1 for d in items if d.kind.value != "一致")

    return {
        "drawing_member_count": len(drawing_set.members),
        "calc_member_count": len(calc_set.members),
        "diff_count": _mismatch_count(diffs),
        "diffs": [d.model_dump() for d in diffs],
        "drawing_slab_count": len(drawing_slabs.slabs),
        "calc_slab_count": len(calc_slabs.slabs),
        "slab_diff_count": _mismatch_count(slab_diffs),
        "slab_diffs": [d.model_dump() for d in slab_diffs],
    }


# ---------------------------------------------------------------------------
# 全件PDFレポート（小梁/スラブ別）
# ---------------------------------------------------------------------------
@app.get("/api/report.pdf")
def report_pdf(
    category: str = Query("beam", pattern="^(beam|slab)$"),
    marks: str | None = None,
) -> Response:
    """指定カテゴリ(小梁/スラブ)の差分を1冊のPDFにまとめて返す。

    marks="A,B,C" を渡すと、その符号のみに限定（表示中フィルタ反映用）。
    marks 未指定なら、そのカテゴリの全差分（「一致」は除く）が対象。
    """
    if not role_paths("drawing") or not role_paths("calc"):
        raise HTTPException(400, "構造図PDFと計算書PDFを両方アップロードしてください")
    drawing_set, drawing_slabs = _parse_drawings()
    calc_set, calc_slabs = _parse_calcs()

    if category == "beam":
        diffs = compare(drawing_set, calc_set)
        label = "小梁"
        summary: dict = {
            "構造図 小梁数": len(drawing_set.members),
            "計算書 小梁数": len(calc_set.members),
            "不整合 全件数": sum(1 for d in diffs if d.kind.value != "一致"),
        }
    else:
        diffs = compare_slabs(drawing_slabs, calc_slabs)
        label = "スラブ"
        summary = {
            "構造図 スラブ数": len(drawing_slabs.slabs),
            "計算書 スラブ数": len(calc_slabs.slabs),
            "不整合 全件数": sum(1 for d in diffs if d.kind.value != "一致"),
        }

    if marks is not None:
        keep = {m.strip() for m in marks.split(",") if m.strip()}
        diffs = [d for d in diffs if d.mark in keep]
        summary["出力対象件数"] = len([d for d in diffs if d.kind.value != "一致"])
        summary["出力条件"] = "表示中の符号のみ"

    pdf = build_report(diffs, label, summary)
    import datetime as _dt
    fn = f"suga_report_{label}_{_dt.datetime.now():%Y%m%d_%H%M}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


# ---------------------------------------------------------------------------
# PDFハイライト画像
# ---------------------------------------------------------------------------
@app.get("/api/highlight/{file_id}")
def highlight(
    file_id: str,
    page: int = Query(1, ge=1),
    x0: float | None = None,
    y0: float | None = None,
    x1: float | None = None,
    y1: float | None = None,
    dx0: float | None = None,
    dy0: float | None = None,
    dx1: float | None = None,
    dy1: float | None = None,
    search: str | None = None,
    zoom: float = Query(2.0, ge=1.0, le=4.0),
    crop: bool = True,
) -> Response:
    """ファイルのページをハイライト画像で返す。

    (x0,y0,x1,y1) = 部材全体（橙枠）、(dx0,dy0,dx1,dy1) = 差分箇所（赤枠）。
    """
    pdf_path = find_path(file_id)
    if pdf_path is None:
        raise HTTPException(404, "ファイルが見つかりません")
    bbox = (x0, y0, x1, y1) if None not in (x0, y0, x1, y1) else None
    diff_bb = (dx0, dy0, dx1, dy1) if None not in (dx0, dy0, dx1, dy1) else None
    png = render_highlight_png(pdf_path, page, bbox=bbox,
                               diff_bboxes=[diff_bb] if diff_bb else None,
                               search=search, zoom=zoom, crop=crop)
    return Response(content=png, media_type="image/png")


# ---------------------------------------------------------------------------
# フロントエンド配信（API ルートの後に登録）
# ---------------------------------------------------------------------------
# index.html はブラウザにキャッシュさせない（exe 更新後に古い画面が
# 表示されて API と食い違うのを防ぐ）。中身がハッシュ付きの assets は
# キャッシュ可。
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

if STATIC_DIR.is_dir():
    _assets = STATIC_DIR / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/")
    def _index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/{full_path:path}")
    def _spa_fallback(full_path: str) -> FileResponse:
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)
