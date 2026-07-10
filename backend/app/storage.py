"""アップロードファイルの管理（DB不使用・ファイルシステムベース）。

各自のPCで動く単一ユーザーのツールのため、案件（プロジェクト）の概念は持たず、
アップロードされた構造図PDF・計算書PDFを UPLOAD_DIR 配下に直接置いて管理する。

  UPLOAD_DIR/
    drawing/  <8桁ID>__<元のファイル名>.pdf
    calc/     <8桁ID>__<元のファイル名>.pdf
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from .config import UPLOAD_DIR

ROLES = ("drawing", "calc")
_SEP = "__"


def _role_dir(role: str) -> Path:
    d = UPLOAD_DIR / role
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize(name: str) -> str:
    """ファイル名から危険な文字を除去（パス区切り等）。"""
    name = Path(name).name
    name = name.replace(_SEP, "_")
    name = re.sub(r"[^\w.\-() 　]", "_", name)
    return name or "file.pdf"


def save_upload(role: str, filename: str, data: bytes) -> dict:
    """1ファイルを保存し、{id, name, role} を返す。"""
    fid = uuid.uuid4().hex[:8]
    safe = _sanitize(filename or "file.pdf")
    stored = _role_dir(role) / f"{fid}{_SEP}{safe}"
    stored.write_bytes(data)
    return {"id": fid, "name": safe, "role": role}


def list_uploads(role: str | None = None) -> list[dict]:
    """アップロード済みファイルの一覧（{id, name, role}）。"""
    out: list[dict] = []
    for r in ([role] if role else list(ROLES)):
        for f in sorted(_role_dir(r).glob(f"*{_SEP}*")):
            fid, _, name = f.name.partition(_SEP)
            out.append({"id": fid, "name": name, "role": r})
    return out


def role_paths(role: str) -> list[tuple[str, Path]]:
    """指定ロールの (id, パス) をアップロード順で返す。

    ファイル名先頭のIDは乱数のため、名前順だと処理順がアップロードの
    たびに変わってしまう（同一符号が複数ファイルにある場合、どちらの
    ファイルの内容が採用されるかまで変わる）。更新時刻→名前の順で
    ソートして決定的にする。
    """
    res: list[tuple[float, str, Path]] = []
    for f in sorted(_role_dir(role).glob(f"*{_SEP}*")):
        fid, _, _ = f.name.partition(_SEP)
        try:
            mt = f.stat().st_mtime
        except OSError:
            mt = 0.0
        res.append((mt, fid, f))
    res.sort(key=lambda t: (t[0], t[2].name))
    return [(fid, f) for _, fid, f in res]


def find_path(file_id: str) -> Path | None:
    """ファイルIDから実体パスを引く。"""
    if not re.fullmatch(r"[0-9a-f]{8}", file_id or ""):
        return None
    for r in ROLES:
        for f in _role_dir(r).glob(f"{file_id}{_SEP}*"):
            return f
    return None


def delete_upload(file_id: str) -> bool:
    p = find_path(file_id)
    if p and p.exists():
        p.unlink()
        return True
    return False


def clear_all() -> None:
    for r in ROLES:
        for f in _role_dir(r).glob(f"*{_SEP}*"):
            f.unlink()
