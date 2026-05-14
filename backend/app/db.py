from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine

from .config import DB_URL


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UploadedFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    role: str  # "drawing" or "calc"
    file_name: str
    stored_path: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
