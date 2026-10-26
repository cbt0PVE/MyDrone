#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练 YOLOv8n → 导出 ONNX → 测推理耗时。对应课程第 3 周。

用法（Windows，有 RTX 4060，最快）:
    python tools/prepare_coco_person.py
    python tools/train_yolo.py                 # 默认 50 epoch
    python tools/train_yolo.py --quick         # 先跑 3 epoch 验流程，10 分钟出结果

用法（Mac，Apple Silicon）:
    python tools/train_yolo.py --device mps --batch 8    # 显存小，batch 调小

产物:
    runs/detect/<name>/weights/best.pt      训练权重
    runs/detect/<name>/weights/best.onnx    导出模型
    runs/detect/<name>/summary.md           指标与耗时汇总（可直接贴进报告）

说明:
    只训练 person 一类，所以 mAP 数字比官方 80 类模型好看，这是正常的。
    报告里要写清楚"单类模型"，别拿去和 COCO 全类榜单比。
"""

import argparse
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def pick_device(explicit):
    """没指定就自动选：有 CUDA 用 0，Mac 用 mps，否则 cpu。"""
    if explicit:
        return explicit
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def benchmark(model_path, images, n=50, imgsz=640, device="cpu"):
    """测平均单张耗时与 FPS。前 5 张热身不算数。"""
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    files = [str(p) for p in images][:n]
    if not files:
        return None

    for f in files[:5]:
        model.predict(f, imgsz=imgsz, device=device, verbose=False)

    t0 = time.perf_counter()
    for f in files:
        model.predict(f, imgsz=imgsz, device=device, verbose=False)
    dt = time.perf_counter() - t0
    per_img = dt / len(files)
    return {"n": len(files), "ms": per_img * 1000, "fps": 1.0 / per_img}


def benchmark_onnx(onnx_path, imgsz=640):
    """有 onnxruntime 就顺便测一下 ONNX；没有就跳过（不装也能跑）。"""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        return None

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    x = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)

    for _ in range(5):
        sess.run(None, {name: x})
    t0 = time.perf_counter()
    n = 20
    for _ in range(n):
        sess.run(None, {name: x})
    dt = (time.perf_counter() - t0) / n
    return {"ms": dt * 1000, "fps": 1.0 / dt}


def main():
    ap = argparse.ArgumentParser(description="训练 YOLOv8n 并导出/测速")
    ap.add_argument("--data", default="datasets/coco_person/dataset.yaml")
    ap.add_argument("--model", default="yolov8n.pt", help="起点权重（自动下载）")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="", help="'', 0, mps, cpu")
    ap.add_argument("--name", default="coco_person")
    ap.add_argument("--quick", action="store_true", help="快速验证流程：3 epoch / 320px")
    ap.add_argument("--no-export", action="store_true", help="不导出 ONNX")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[X] 没装 ultralytics：pip install ultralytics")
        return 1

    data = Path(args.data)
    if not data.exists():
        print(f"[X] 数据集不存在：{data}")
        print("    先跑：python tools/prepare_coco_person.py")
        return 1

    if args.quick:
        args.epochs, args.imgsz = 3, 320
        print("[提示] quick 模式：3 epoch / 320px，只验证流程，指标没有参考价值")

    device = pick_device(args.device)
    print(f"设备 {device} | 数据 {data} | epochs {args.epochs} | imgsz {args.imgsz} | batch {args.batch}")

    model = YOLO(args.model)
    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        name=args.name,
        project="runs/detect",
        # 课程数据集小，关掉一些昂贵的增强，训练更快也更稳
        mosaic=0.5,
        close_mosaic=5 if args.epochs > 10 else 0,
        plots=True,
        verbose=True,
    )

    run_dir = Path(model.trainer.save_dir)
    best = run_dir / "weights" / "best.pt"
    print(f"\n训练完成：{best}")

    # ---------- 验证指标 ----------
    metrics = model.val(data=str(data), imgsz=args.imgsz, device=device, verbose=False)
    m50 = float(metrics.box.map50)
    m5095 = float(metrics.box.map)
    print(f"mAP@0.5 = {m50:.4f} | mAP@0.5:0.95 = {m5095:.4f}")

    # ---------- 导出 ----------
    onnx_path = None
    if not args.no_export:
        try:
            onnx_path = Path(model.export(format="onnx", imgsz=args.imgsz, simplify=True))
            print(f"已导出：{onnx_path}")
        except Exception as e:
            print(f"[!] 导出失败（可忽略，权重仍可用）：{e}")

    # ---------- 测速 ----------
    val_images = sorted((data.parent / "images" / "val").glob("*.jpg"))
    bench = benchmark(best, val_images, n=50, imgsz=args.imgsz, device=device) if val_images else None
    bench_onnx = benchmark_onnx(onnx_path, args.imgsz) if onnx_path else None

    # ---------- 汇总 ----------
    lines = [
        f"# 训练汇总：{args.name}",
        "",
        f"- 数据：`{data}`",
        f"- 设备：`{device}`",
        f"- epochs：{args.epochs}   imgsz：{args.imgsz}   batch：{args.batch}",
        f"- mAP@0.5：**{m50:.4f}**",
        f"- mAP@0.5:0.95：{m5095:.4f}",
        "",
        "## 推理耗时",
        "",
    ]
    if bench:
        lines.append(f"- PyTorch `best.pt`：{bench['ms']:.1f} ms/张 → **{bench['fps']:.1f} FPS**"
                     f"（{bench['n']} 张平均，{device}）")
    if bench_onnx:
        lines.append(f"- ONNX Runtime（CPU）：{bench_onnx['ms']:.1f} ms/张 → {bench_onnx['fps']:.1f} FPS")
    lines += [
        "",
        "> 注意：这是**单类（person）**模型，mAP 不能和 COCO 80 类榜单直接比。",
        "> 机载端（香橙派 RK3588S + RKNN INT8）的帧率需要到板子上重新测。",
    ]
    summary_path = run_dir / "summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n汇总已写入：{summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
