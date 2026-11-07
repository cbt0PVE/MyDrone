# -*- coding: utf-8 -*-
"""在板上跑一段视频：open_camera → 检测器 → 标注/保存 → FPS。

    bash run_with_rknn.sh python3 tools/video_pipeline.py \
        --source ~/person_pan.avi --model ~/best_heads.rknn \
        --out ~/person_pan_out.avi

用途：相机到货前验证连续取图 + RKNN 检测的稳定性。
"""

import argparse
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnav.camera import open_camera  # noqa: E402
from vnav.config import Config, load_camera_matrix  # noqa: E402
from vnav.detectors import build_detector  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="板上视频检测流水线")
    ap.add_argument("--source", required=True, help="视频路径或摄像头序号")
    ap.add_argument("--model", required=True, help=".rknn / .onnx / .pt")
    ap.add_argument("--out", default="", help="输出标注视频（.avi），空=不写")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--mot", action="store_true", help="启用多目标跟踪 + 目标锁定")
    ap.add_argument("--mot-predict", action="store_true",
                    help="演示用：丢失时返回预测框；飞行不要开（安全看门狗会看不到丢失）")
    ap.add_argument("--max-frames", type=int, default=0, help="0=全部")
    args = ap.parse_args()

    cfg = Config()
    cfg.camera_source = args.source
    cfg.yolo_weights = args.model
    cfg.yolo_conf = args.conf
    cfg.use_mot = args.mot
    cfg.mot_allow_predict = args.mot_predict
    cfg.show_window = False

    K, dist, note = load_camera_matrix(cfg)
    print("intrinsics:", note)
    detector = build_detector(cfg, K, dist)
    cap = open_camera(cfg)
    print("source:", cap.describe())

    writer = None
    frames = 0
    hits = 0
    t0 = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if args.max_frames and frames >= args.max_frames:
                break

            det = detector.detect(frame)
            if det is not None:
                hits += 1
                cx, cy = int(det.center_px[0]), int(det.center_px[1])
                cv2.circle(frame, (cx, cy), 8, (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    "id=%s fwd=%.2fm conf=%.2f"
                    % (det.marker_id, det.forward_m, det.confidence),
                    (max(0, cx - 80), max(20, cy - 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    1,
                    cv2.LINE_AA,
                )

            if args.out and writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(
                    args.out, cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (w, h)
                )
                print("writer:", args.out, (w, h))
            if writer is not None:
                writer.write(frame)

            frames += 1
            if frames % 20 == 0:
                fps = frames / max(1e-6, time.perf_counter() - t0)
                print("frames=%d hits=%d fps=%.1f" % (frames, hits, fps))
    finally:
        cap.release()
        if writer is not None:
            writer.release()

    elapsed = time.perf_counter() - t0
    print("---- summary ----")
    print("frames=%d hits=%d elapsed=%.2fs fps=%.1f" % (frames, hits, elapsed, frames / max(1e-6, elapsed)))


if __name__ == "__main__":
    main()
