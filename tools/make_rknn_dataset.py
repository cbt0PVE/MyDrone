# -*- coding: utf-8 -*-
"""生成 RKNN 量化用的图片列表（每行一个绝对路径）。

    python tools/make_rknn_dataset.py \
        --images datasets/coco_person/images/train \
        --limit 100 --output /tmp/rknn_dataset.txt

建议 100–200 张，覆盖：单人、多人、远近、不同背景。
"""

import argparse
import os
from pathlib import Path

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main():
    ap = argparse.ArgumentParser(description="生成 RKNN 量化图片列表")
    ap.add_argument("--images", required=True, help="图片目录（递归）")
    ap.add_argument("--output", required=True, help="输出 txt")
    ap.add_argument("--limit", type=int, default=100, help="最多几张，默认 100")
    args = ap.parse_args()

    root = Path(args.images).resolve()
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXTS
    )
    if not files:
        raise SystemExit(f"没有找到图片: {root}")

    files = files[: max(1, args.limit)]
    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(str(p) for p in files) + "\n", encoding="utf-8")
    print(f"OK {len(files)} 张 -> {out}")


if __name__ == "__main__":
    main()
