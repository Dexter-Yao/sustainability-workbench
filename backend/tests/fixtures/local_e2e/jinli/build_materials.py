# ABOUTME(en): Converts the Markdown sources under materials/ into uploadable docx files, one to one, without merging or rewriting.
# ABOUTME(en): Uses pandoc; the output is a semantic material format the product accepts (.md is not admitted).
"""把 materials/*.md 转为 materials_docx/*.docx。

产品语义资料仅接受 .pdf/.docx/.xlsx/.pptx（`material_workspace_service.py:82`），
Markdown 源文保留在版本控制中便于审阅与改写，docx 为派生产物。

用法（在 backend/ 下）：
    uv run python tests/fixtures/local_e2e/jinli/build_materials.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = FIXTURE_DIR / "materials"
DEFAULT_OUT_DIR = FIXTURE_DIR / "materials_docx"

def convert(out_dir: Path) -> list[Path]:
    if shutil.which("pandoc") is None:
        raise SystemExit("未找到 pandoc，无法转换 docx")

    sources = sorted(SOURCE_DIR.glob("*.md"))
    if not sources:
        raise SystemExit(f"{SOURCE_DIR} 下没有 Markdown 源文")

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source in sources:
        target = out_dir / f"{source.stem}.docx"
        subprocess.run(
            ["pandoc", str(source), "-o", str(target)],
            check=True,
            capture_output=True,
        )
        written.append(target)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    written = convert(args.out_dir)
    total = sum(path.stat().st_size for path in written)
    print(f"已转换 {len(written)} 份 docx → {args.out_dir}（合计 {total / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
