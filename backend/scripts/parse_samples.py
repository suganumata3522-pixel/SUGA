"""アップロードされた構造図PDF と計算書PDF をパースし、差分を表示する。

実行:
    python -m scripts.parse_samples <drawing.pdf> <calc.pdf>
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.checker import compare, compare_slabs
from app.parsers import DrawingPdfParser, StructureSuitePdfParser, parse_calc_slabs, parse_drawing_slabs


def _dump_set(label, ms):
    print(f"\n=== {label}: {ms.file_name} ({len(ms.members)} members) ===")
    for m in ms.members:
        print(f"- {m.mark:8} B={m.section.B} D={m.section.D} Fc={m.concrete_grade or m.fc_code}")
        for p in m.positions:
            print(f"    [{p.location}] 上:{p.top}  下:{p.bottom}  STP:{p.stirrup}  腹:{p.web}")


def _dump_diffs(label: str, diffs) -> None:
    print(f"\n=== {label}: {len(diffs)} 件 ===")
    for d in diffs:
        line = f"  [{d.kind.value}] {d.mark}"
        for f in d.fields:
            line += f"\n      {f.field}: 図={f.drawing_value} / 計算={f.calc_value}"
        print(line)


def main(drawing_path: str, calc_path: str) -> None:
    drawing = DrawingPdfParser().parse(Path(drawing_path))
    calc = StructureSuitePdfParser().parse(Path(calc_path))
    _dump_set("DRAWING", drawing)
    _dump_set("CALC", calc)
    _dump_diffs("DIFF (小梁)", compare(drawing, calc))

    # スラブ
    d_slabs = parse_drawing_slabs(Path(drawing_path))
    c_slabs = parse_calc_slabs(Path(calc_path))
    print(f"\n=== SLABS: 図 {len(d_slabs.slabs)} 枚 / 計算 {len(c_slabs.slabs)} 枚 ===")
    _dump_diffs("DIFF (スラブ)", compare_slabs(d_slabs, c_slabs))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.parse_samples <drawing.pdf> <calc.pdf>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
