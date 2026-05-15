from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlmodel import select

from .checker import Diff, compare
from .config import UPLOAD_DIR
from .db import Project, UploadedFile, get_session, init_db
from .models import MemberSet
from .parsers import DrawingPdfParser, StructureSuitePdfParser

app = FastAPI(title="SUGA - 構造図/計算書整合チェック", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/projects")
def create_project(name: str = Form(...)) -> dict:
    with get_session() as s:
        p = Project(name=name)
        s.add(p)
        s.commit()
        s.refresh(p)
        return {"id": p.id, "name": p.name}


@app.get("/api/projects")
def list_projects() -> list[dict]:
    with get_session() as s:
        items = s.exec(select(Project)).all()
        return [{"id": p.id, "name": p.name, "created_at": p.created_at.isoformat()} for p in items]


def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "").suffix or ".pdf"
    stored = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with stored.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return stored


@app.post("/api/projects/{project_id}/uploads")
def upload_file(project_id: int, role: str = Form(...), file: UploadFile = File(...)) -> dict:
    if role not in {"drawing", "calc"}:
        raise HTTPException(400, "role must be 'drawing' or 'calc'")
    stored = _save_upload(file)
    with get_session() as s:
        rec = UploadedFile(
            project_id=project_id,
            role=role,
            file_name=file.filename or stored.name,
            stored_path=str(stored),
        )
        s.add(rec)
        s.commit()
        s.refresh(rec)
        return {"id": rec.id, "file_name": rec.file_name, "role": rec.role}


@app.post("/api/projects/{project_id}/check")
def run_check(project_id: int, calc_software: str = Form("ss")) -> dict:
    with get_session() as s:
        uploads = s.exec(select(UploadedFile).where(UploadedFile.project_id == project_id)).all()
    drawing = next((u for u in uploads if u.role == "drawing"), None)
    calc = next((u for u in uploads if u.role == "calc"), None)
    if not drawing or not calc:
        raise HTTPException(400, "drawing と calc の両方をアップロードしてください")

    drawing_set: MemberSet = DrawingPdfParser().parse(Path(drawing.stored_path))
    calc_set: MemberSet = StructureSuitePdfParser().parse(Path(calc.stored_path))
    _ = calc_software  # 将来 SS7/SS3 を実装したら分岐

    diffs: list[Diff] = compare(drawing_set, calc_set)
    return {
        "drawing_member_count": len(drawing_set.members),
        "calc_member_count": len(calc_set.members),
        "diff_count": len(diffs),
        "diffs": [d.model_dump() for d in diffs],
    }


def _uploaded_pdf_path(project_id: int, role: str) -> Path:
    with get_session() as s:
        upload = s.exec(
            select(UploadedFile)
            .where(UploadedFile.project_id == project_id)
            .where(UploadedFile.role == role)
            .order_by(UploadedFile.id.desc())
        ).first()
    if not upload:
        raise HTTPException(404, f"{role} がアップロードされていません")
    path = Path(upload.stored_path)
    if not path.exists():
        raise HTTPException(404, f"PDFファイルが見つかりません: {path}")
    return path


@app.get("/api/projects/{project_id}/highlight")
def highlight(
    project_id: int,
    role: str = Query(..., pattern="^(drawing|calc)$"),
    page: int = Query(1, ge=1),
    x0: float | None = None,
    y0: float | None = None,
    x1: float | None = None,
    y1: float | None = None,
    search: str | None = None,
    zoom: float = Query(2.0, ge=1.0, le=4.0),
) -> Response:
    """指定ページを画像にレンダリングし、bbox or 検索ヒットを枠で強調して返す。"""
    pdf_path = _uploaded_pdf_path(project_id, role)
    doc = fitz.open(pdf_path)
    try:
        if page > doc.page_count:
            raise HTTPException(400, f"ページ {page} はPDFの範囲外です (max {doc.page_count})")
        pg = doc.load_page(page - 1)

        rects: list[fitz.Rect] = []
        if x0 is not None and y0 is not None and x1 is not None and y1 is not None:
            rects.append(fitz.Rect(x0, y0, x1, y1))
        elif search:
            hits = pg.search_for(search)
            # 範囲を少し膨らませる（前後行も含めて見やすく）
            for r in hits:
                rects.append(fitz.Rect(r.x0 - 10, r.y0 - 4, r.x1 + 80, r.y1 + 4))

        # 枠線を描画（オレンジ、太線）。
        # pdfplumber は回転後の表示座標、search_for は表示座標を返すが、
        # draw_rect は未回転の PDF 座標を要求するため derotation を適用する。
        derotate = pg.derotation_matrix
        for r in rects:
            pg.draw_rect(r * derotate, color=(1, 0.5, 0), width=2.5)

        mat = fitz.Matrix(zoom, zoom)
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        buf = io.BytesIO(pix.tobytes("png"))
        return Response(content=buf.getvalue(), media_type="image/png")
    finally:
        doc.close()
