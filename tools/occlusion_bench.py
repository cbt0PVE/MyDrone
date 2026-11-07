# -*- coding: utf-8 -*-
"""遮挡基准：黑块挡住目标 N 帧，看 MOT 是否保住同一个 ID。

    bash run_with_rknn.sh python3 tools/occlusion_bench.py \
        --video ~/occl_20.avi --model ~/best_heads.rknn \
        --start 50 --frames 20

输出：遮挡前 ID、遮挡期间 None 帧数、遮挡后首个 ID、重捕获帧数、是否保持。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnav.camera import open_camera  # noqa: E402
from vnav.config import Config, load_camera_matrix  # noqa: E402
from vnav.detectors import build_detector  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="遮挡 ID 保持基准")
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--start", type=int, default=50, help="第一次被挡的帧号")
    ap.add_argument("--frames", type=int, required=True, help="挡多少帧（20fps）")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--max-age", type=int, default=45, help="轨迹丢失多少帧后删除")
    ap.add_argument("--max-lost", type=int, default=45, help="锁定目标丢失多少帧后放弃重捕获")
    args = ap.parse_args()

    cfg = Config()
    cfg.camera_source = args.video
    cfg.yolo_weights = args.model
    cfg.yolo_conf = args.conf
    cfg.show_window = False
    cfg.use_mot = True
    cfg.mot_max_age = args.max_age
    cfg.mot_max_lost = args.max_lost
    cfg.mot_allow_predict = False

    K, _, _ = load_camera_matrix(cfg)
    detector = build_detector(cfg, K, None)
    cap = open_camera(cfg)

    ids = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            det = detector.detect(frame)
            ids.append(None if det is None else int(det.marker_id))
    finally:
        cap.release()

    start = args.start
    n = args.frames
    pre = [i for i in ids[max(0, start - 10):start] if i is not None]
    before = max(set(pre), key=pre.count) if pre else None
    during = ids[start:start + n]
    after = None
    reacq = None
    for idx in range(start + n, len(ids)):
        if ids[idx] is not None:
            after = ids[idx]
            reacq = idx - (start + n)
            break

    # 非 None 的 ID 变化次数
    seq = [i for i in ids if i is not None]
    switches = sum(1 for a, b in zip(seq, seq[1:]) if a != b)

    print("video", os.path.basename(args.video), "max_age", args.max_age, "max_lost", args.max_lost)
    print("frames", len(ids), "occlusion", n)
    print("before_id", before)
    print("during_none", sum(1 for i in during if i is None), "/", n)
    print("after_id", after, "reacquire_frames", reacq)
    print("retained", bool(before is not None and after == before))
    print("id_switches", switches)


if __name__ == "__main__":
    main()
