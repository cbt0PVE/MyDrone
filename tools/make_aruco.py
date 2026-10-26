#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可打印的 ArUco 标签（按真实物理尺寸出图，打印后不用缩放）。

用法:
    python tools/make_aruco.py                          # id=7, 120mm
    python tools/make_aruco.py --id 3 --size-mm 150     # 换 id 和尺寸
    python tools/make_aruco.py --out markers/a4.png --per-sheet 4

打印注意:
    1. 用"实际大小 / 100%"打印，不要选"适应页面"，否则尺寸就错了。
    2. 打印完拿尺子量一下黑框边长，必须等于 --size-mm。
    3. 量出来多少，就在 config.py 里把 marker_size_m 写成多少（单位米）。
"""

import argparse
import os

import cv2
import numpy as np


def make_marker(marker_id: int, dict_name: str, size_mm: float, dpi: int = 300):
    """返回一张带白边的灰度图，黑色方块（含边框）的物理边长就是 size_mm。"""
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dict_name))

    # 把毫米换成像素：1 英寸 = 25.4mm
    side_px = int(round(size_mm / 25.4 * dpi))
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, side_px)

    # ArUco 的识别需要四周留白（quiet zone），否则边缘对比度不够会识别失败。
    # 规范建议至少 1 个格子的宽度，这里留 20% 比较保险。
    margin = int(round(side_px * 0.2))
    canvas = np.full(
        (side_px + 2 * margin, side_px + 2 * margin), 255, dtype=np.uint8
    )
    canvas[margin : margin + side_px, margin : margin + side_px] = marker
    return canvas, side_px, margin


def add_caption(img: np.ndarray, text: str) -> np.ndarray:
    """在底部加一行说明，方便打印后一眼看出是哪个 id、多大。"""
    h, w = img.shape[:2]
    bar = 60
    canvas = np.full((h + bar, w), 255, dtype=np.uint8)
    canvas[:h, :] = img
    cv2.putText(
        canvas, text, (10, h + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 2, cv2.LINE_AA
    )
    return canvas


def main():
    ap = argparse.ArgumentParser(description="生成可打印的 ArUco 标签")
    ap.add_argument("--id", type=int, default=7, help="标签 ID")
    ap.add_argument("--dict", default="DICT_4X4_50", help="字典名")
    ap.add_argument("--size-mm", type=float, default=120.0, help="黑框边长 mm")
    ap.add_argument("--dpi", type=int, default=300, help="打印 DPI")
    ap.add_argument("--out", default=None, help="输出路径")
    ap.add_argument("--no-caption", action="store_true", help="不加底部说明")
    args = ap.parse_args()

    img, side_px, margin = make_marker(args.id, args.dict, args.size_mm, args.dpi)
    if not args.no_caption:
        img = add_caption(
            img, f"ArUco {args.dict} id={args.id}  {args.size_mm:.0f}mm  {args.dpi}dpi"
        )

    out = args.out or f"markers/aruco_{args.dict.lower()}_id{args.id}_{int(args.size_mm)}mm.png"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cv2.imwrite(out, img)

    print(f"已生成 {out}")
    print(f"  黑框 {side_px}px = {args.size_mm:.1f}mm @ {args.dpi}dpi，四周留白 {margin}px")
    print(f"  打印时选「实际大小 100%」，打完用尺子量黑框边长，应为 {args.size_mm:.0f}mm")
    print(f"  量完把 config.py 里 marker_size_m 改成 {args.size_mm/1000:.3f}")


if __name__ == "__main__":
    main()
