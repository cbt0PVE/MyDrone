#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 COCO val2017 生成「只有 person 一类」的 YOLO 数据集。

为什么用 COCO：
    - 现成、标注质量高、不需要自己标；
    - 只取 person 一类后大约 2600 张图，规模适合课程级训练（4060 上几十分钟）。

为什么用 val2017 而不是 train2017：
    train2017 有 118k 张、19GB，抽 person 也有 6 万多张，训练要几个小时。
    val2017 只有 5000 张（约 800MB），过滤后够用，而且下载和磁盘压力都小。

用法:
    python tools/prepare_coco_person.py                # 下载 + 生成，约 1GB 下载
    python tools/prepare_coco_person.py --min-height 60 # 过滤掉太小的行人
    python tools/prepare_coco_person.py --no-download   # 已下过，只重新生成

产物（默认在 datasets/coco_person/）：
    images/train/*.jpg  images/val/*.jpg
    labels/train/*.txt  labels/val/*.txt
    dataset.yaml            <- 直接喂给训练脚本
"""

import argparse
import json
import random
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

COCO_BASE = "http://images.cocodataset.org"
FILES = {
    "val2017.zip": f"{COCO_BASE}/zips/val2017.zip",
    "annotations_trainval2017.zip": f"{COCO_BASE}/annotations/annotations_trainval2017.zip",
}

# COCO 里 category_id = 1 就是 person
PERSON_ID = 1


def download(url: str, dst: Path) -> None:
    """带进度条下载。已经存在就跳过。"""
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  已存在，跳过下载：{dst.name}")
        return

    print(f"  下载 {url}")
    print(f"    -> {dst}")

    def hook(blocks, block_size, total):
        if total > 0:
            done = blocks * block_size / total * 100
            print(f"\r    {done:5.1f}%  ({blocks * block_size / 1e6:.0f}/{total / 1e6:.0f} MB)",
                  end="", flush=True)

    urllib.request.urlretrieve(url, dst, reporthook=hook)
    print("")


def unzip(src: Path, dst: Path) -> None:
    print(f"  解压 {src.name} ...")
    with zipfile.ZipFile(src) as zf:
        zf.extractall(dst)


def load_person_boxes(ann_file: Path, min_w: int, min_h: int):
    """返回 {文件名: [(x, y, w, h), ...]}，只保留 person 且尺寸够大的框。"""
    print(f"  读取标注 {ann_file.name} ...")
    with open(ann_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    name_by_id = {img["id"]: img["file_name"] for img in data["images"]}
    size_by_name = {
        img["file_name"]: (img["width"], img["height"]) for img in data["images"]
    }

    boxes = {}
    skipped_crowd = 0
    skipped_small = 0

    for ann in data["annotations"]:
        if ann["category_id"] != PERSON_ID:
            continue
        if ann.get("iscrowd", 0):
            skipped_crowd += 1
            continue
        x, y, w, h = ann["bbox"]
        if w < min_w or h < min_h:
            skipped_small += 1
            continue
        name = name_by_id[ann["image_id"]]
        boxes.setdefault(name, []).append((x, y, w, h))

    print(f"    含人的图 {len(boxes)} 张，跳过拥挤标注 {skipped_crowd} 个、"
          f"过小目标 {skipped_small} 个")
    return boxes, size_by_name


def to_yolo_line(box, img_w, img_h):
    """COCO 的 [x, y, w, h]（左上角+宽高，像素）-> YOLO 的 [cx, cy, w, h]（归一化）。"""
    x, y, w, h = box
    # 裁剪到画面内，防止越界标注把归一化值算出负数
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(float(img_w), x + w), min(float(img_h), y + h)
    if x2 <= x1 or y2 <= y1:
        return None
    cx = (x1 + x2) / 2 / img_w
    cy = (y1 + y2) / 2 / img_h
    bw = (x2 - x1) / img_w
    bh = (y2 - y1) / img_h
    return f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def main():
    ap = argparse.ArgumentParser(description="生成 COCO person 子集（YOLO 格式）")
    ap.add_argument("--out", default="datasets/coco_person", help="输出目录")
    ap.add_argument("--cache", default="data/coco_raw", help="下载与解压缓存目录")
    ap.add_argument("--val-ratio", type=float, default=0.15, help="验证集比例")
    ap.add_argument("--min-width", type=int, default=16, help="最小框宽（像素）")
    ap.add_argument("--min-height", type=int, default=40, help="最小框高（像素）")
    ap.add_argument("--seed", type=int, default=0, help="划分随机种子")
    ap.add_argument("--no-download", action="store_true", help="只用已有缓存")
    args = ap.parse_args()

    out = Path(args.out)
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 准备原始数据 ----------
    if not args.no_download:
        print("[1/4] 下载 COCO val2017 与标注 ...")
        for name, url in FILES.items():
            download(url, cache / name)

    val_dir = cache / "val2017"
    ann_file = cache / "annotations" / "instances_val2017.json"

    if not val_dir.exists():
        z = cache / "val2017.zip"
        if not z.exists():
            print(f"[X] 缺少 {z}，去掉 --no-download 重新跑一次")
            return 1
        unzip(z, cache)

    if not ann_file.exists():
        z = cache / "annotations_trainval2017.zip"
        if not z.exists():
            print(f"[X] 缺少 {z}，去掉 --no-download 重新跑一次")
            return 1
        unzip(z, cache)

    if not ann_file.exists():
        print(f"[X] 找不到标注文件 {ann_file}")
        return 1

    # ---------- 2. 过滤 ----------
    print("[2/4] 过滤 person 标注 ...")
    boxes, sizes = load_person_boxes(ann_file, args.min_width, args.min_height)
    names = sorted(boxes.keys())
    if not names:
        print("[X] 一张含人的图都没找到，检查标注文件是否完整")
        return 1

    # ---------- 3. 划分 ----------
    rng = random.Random(args.seed)
    rng.shuffle(names)
    n_val = max(1, int(len(names) * args.val_ratio))
    split = {"val": names[:n_val], "train": names[n_val:]}

    # ---------- 4. 写盘 ----------
    print("[3/4] 写出 YOLO 格式 ...")
    for sub in ("train", "val"):
        (out / "images" / sub).mkdir(parents=True, exist_ok=True)
        (out / "labels" / sub).mkdir(parents=True, exist_ok=True)

    written = {"train": 0, "val": 0}
    for sub, files in split.items():
        for name in files:
            src = val_dir / name
            if not src.exists():
                continue
            w, h = sizes[name]
            lines = [to_yolo_line(b, w, h) for b in boxes[name]]
            lines = [ln for ln in lines if ln]
            if not lines:
                continue

            shutil.copy2(src, out / "images" / sub / name)
            with open(out / "labels" / sub / (Path(name).stem + ".txt"), "w") as f:
                f.write("\n".join(lines) + "\n")
            written[sub] += 1

    # dataset.yaml 用绝对路径，避免 ultralytics 在别的工作目录下找不到图
    yaml_path = out / "dataset.yaml"
    yaml_path.write_text(
        f"# 由 tools/prepare_coco_person.py 自动生成\n"
        f"path: {out.resolve().as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"names:\n  0: person\n",
        encoding="utf-8",
    )

    print("[4/4] 完成")
    print(f"  训练集 {written['train']} 张 / 验证集 {written['val']} 张")
    print(f"  数据集定义：{yaml_path}")
    print("")
    print("下一步：python tools/train_yolo.py --data " + str(yaml_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
