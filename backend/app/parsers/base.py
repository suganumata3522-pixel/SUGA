from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import MemberSet, Source


class Parser(ABC):
    source: Source

    @abstractmethod
    def parse(self, pdf_path: Path) -> MemberSet: ...
