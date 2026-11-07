# -*- coding: utf-8 -*-
"""在板上对比 ONNX 与 RKNN 的检测框（批量）。

    bash run_with_rknn.sh python3 tools/eval_rknn_batch.py \
        --onnx ~/best.onnx --rknn ~/best_heads.rknn --images ~/imgs40 --conf 0.35

输出：
- best-match IoU：ONNX top 框与 RKNN 所有候选里的最大 IoU（推荐指标）
- top1 IoU：两边各自最高分框的 IoU（多人图会被“选不同的人”拉低）
- 分数差、检出数、漏配数

注意：必须在板上、且用 run_with_rknn.sh 包裹（否则会加载 1.4.0 运行时）。
"""

import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnav.config import Config  # noqa: E402
from vnav.detectors import OnnxDetector, RknnDetector  # noqa: E402


def iou_one(box, boxes):
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    aa = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    bb = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(1e-9, aa + bb - inter)


def main():
    ap = argparse.ArgumentParser(description="批量对比 ONNX / RKNN 检测框")
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--rknn", required=True)
    ap.add_argument("--images", required=True, help="图片目录（递归 jpg/png）")
    ap.add_argument("--conf", type=float, default=0.35, help="检出阈值，默认 0.35")
    ap.add_argument("--limit", type=int, default=0, help="最多几张，0=全部")
    args = ap.parse_args()

    files = sorted(
        p for p in glob.glob(os.path.join(args.images, "**", "*"), recursive=True)
        if os.path.isfile(p) and p.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"没有图片: {args.images}")

    cfg = Config()
    cfg.yolo_conf = 0.0  # 先取全部候选，阈值后面单独算
    K = np.eye(3)
    cfg.yolo_weights = args.onnx
    onnx = OnnxDetector(cfg, K)
    onnx._load()
    rknn = RknnDetector(cfg, K, model_path=args.rknn)
    rknn._load()

    best_ious, top1_ious, score_diffs = [], [], []
    det_o = det_r = missed = 0
    for path in files:
        img = cv2.imread(path)
        if img is None:
            continue

        blob, _, _, _ = onnx._letterbox(img, onnx._input_hw)
        xy_o, s_o = onnx._decode(onnx._infer(blob)[0], 0.0, 1)

        blob2, _, _, _ = rknn._letterbox(img, rknn._input_hw)
        xy_r, s_r = rknn._decode_heads(rknn._infer(blob2))
        if len(s_o) == 0 or len(s_r) == 0:
            continue

        io = int(np.argmax(s_o))
        ir = int(np.argmax(s_r))
        so, sr = float(s_o[io]), float(s_r[ir])
        best = float(iou_one(xy_o[io], xy_r).max())
        top1 = float(iou_one(xy_o[io], xy_r[ir:ir + 1])[0])
        best_ious.append(best)
        top1_ious.append(top1)
        score_diffs.append(abs(so - sr))

        do, dr = so >= args.conf, sr >= args.conf
        det_o += int(do)
        det_r += int(dr)
        if do and not dr:
            missed += 1

    print("images", len(best_ious))
    print("best-match iou mean=%.4f min=%.4f" % (np.mean(best_ious), np.min(best_ious)))
    print("top1       iou mean=%.4f min=%.4f" % (np.mean(top1_ious), np.min(top1_ious)))
    print("abs score diff mean=%.4f max=%.4f" % (np.mean(score_diffs), np.max(score_diffs)))
    print("det@%.2f onnx=%d rknn=%d missed=%d" % (args.conf, det_o, det_r, missed))


if __name__ == "__main__":
    main()
