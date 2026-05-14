"""アップロードされた構造図PDF と計算書PDF をパースし、差分を表示する。

実行:
    python -m scripts.parse_samples <drawing.pdf> <calc.pdf>
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.checker import compare
from app.parsers import DrawingPdfParser, StructureSuitePdfParser


def _dump_set(label, ms):
    print(f"\n=== {label}: {ms.file_name} ({len(ms.members)} members) ===")
    for m in ms.members:
        print(f"- {m.mark:8} B={m.section.B} D={m.section.D} Fc={m.concrete_grade or m.fc_code}")
        for p in m.positions:
            print(f"    [{p.location}] 上:{p.top}  下:{p.bottom}  STP:{p.stirrup}  腹:{p.web}")


def main(drawing_path: str, calc_path: str) -> None:
    drawing = DrawingPdfParser().parse(Path(drawing_path))
    calc = StructureSuitePdfParser().parse(Path(calc_path))
    _dump_set("DRAWING", drawing)
    _dump_set("CALC", calc)
    diffs = compare(drawing, calc)
    print(f"\n=== DIFF: {len(diffs)} 件 ===")
    for d in diffs:
        line = f"  [{d.kind.value}] {d.mark}"
        for f in d.fields:
            line += f"\n      {f.field}: 図={f.drawing_value} / 計算={f.calc_value}"
        print(line)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.parse_samples <drawing.pdf> <calc.pdf>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
