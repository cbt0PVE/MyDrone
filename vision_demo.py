#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯视觉演示：只开摄像头识别 ArUco，不连飞控。

这个脚本在 Mac 上就能跑（只需要 opencv + numpy），用来：
    - 确认摄像头、标签、光照能识别到
    - 检查测出来的距离是否接近真实值（验证标定/标签边长）
    - 课上演示视觉部分

用法:
    python vision_demo.py                 # 默认摄像头 0
    python vision_demo.py --camera 1 --marker-size 0.15
    python vision_demo.py --print-only    # 不弹窗，只打印（SSH/无界面时用）

退出：窗口里按 q，或终端 Ctrl+C。
"""

import argparse
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

import cv2

from vnav.config import Config, load_camera_matrix, parse_camera_source
from vnav.vision import ArucoTracker


def main():
    ap = argparse.ArgumentParser(description="ArUco 纯视觉演示")
    ap.add_argument(
        "--camera",
        default="0",
        help='摄像头：0/1 或视频流地址，如 "http://192.168.1.23:8080/video"',
    )
    ap.add_argument("--marker-size", type=float, default=None, help="标签边长 m")
    ap.add_argument("--calib", default=None, help="标定文件 json")
    ap.add_argument("--print-only", action="store_true", help="不弹窗只打印")
    args = ap.parse_args()

    cfg = Config()
    cfg.camera_source = parse_camera_source(args.camera)
    if args.marker_size:
        cfg.marker_size_m = args.marker_size
    if args.calib:
        cfg.calib_path = args.calib

    K, dist, note = load_camera_matrix(cfg)
    print(f"相机内参：{note}")
    print(f"标签边长：{cfg.marker_size_m*100:.1f} cm，字典 {cfg.aruco_dict}")
    print("窗口里按 q 退出")
    print("")

    tracker = ArucoTracker(cfg, K, dist)

    cap = cv2.VideoCapture(cfg.camera_source)
    if not cap.isOpened():
        print(f"[X] 打不开摄像头 {cfg.camera_source!r}")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.frame_height)

    last = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            det = tracker.detect(frame)
            now = time.time()
            if now - last > 0.3:  # 限频打印，别刷屏
                last = now
                if det is None:
                    print("未识别到标签")
                else:
                    print(
                        f"id={det.marker_id} | 前 {det.forward_m:+.3f} "
                        f"右 {det.right_m:+.3f} 下 {det.down_m:.3f} m | "
                        f"像素 ({det.center_px[0]:.0f},{det.center_px[1]:.0f})"
                    )

            if det is not None:
                cx, cy = int(det.center_px[0]), int(det.center_px[1])
                cv2.drawMarker(frame, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 24, 2)
                cv2.putText(
                    frame,
                    f"{det.down_m:.2f}m",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )

            if not args.print_only:
                cv2.imshow("ArUco demo", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
