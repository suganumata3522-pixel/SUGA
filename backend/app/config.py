import os
from pathlib import Path

DB_URL = os.environ.get("SUGA_DB_URL", "sqlite:///./data/suga.db")
UPLOAD_DIR = Path(os.environ.get("SUGA_UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
