from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
