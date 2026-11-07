# -*- coding: utf-8 -*-
"""MOT / 目标锁定回归测试（不接相机、不接飞控）。"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.mot import IouTracker, TargetSelector, TrackingDetector  # noqa: E402
from vnav.vision import Detection  # noqa: E402


def det(x1, y1, x2, y2, conf=0.9):
    return Detection(
        marker_id=-1,
        center_px=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
        forward_m=3.0,
        right_m=0.0,
        down_m=0.0,
        yaw_deg=0.0,
        tvec=np.zeros(3),
        confidence=conf,
        bbox=(float(x1), float(y1), float(x2), float(y2)),
    )


def box(x, y, w=100, h=200):
    return det(x, y, x + w, y + h)


def test_ids_persist_across_frames():
    tr = IouTracker(iou_threshold=0.3, max_age=10, min_hits=1)
    tr.update([box(100, 100), box(400, 100)])
    ids1 = sorted(t.track_id for t in tr.tracks)
    tr.update([box(110, 100), box(410, 100)])
    ids2 = sorted(t.track_id for t in tr.tracks)
    assert ids1 == ids2 == [1, 2]


def test_occlusion_keeps_id():
    tr = IouTracker(iou_threshold=0.3, max_age=10, min_hits=1)
    tr.update([box(100, 100), box(400, 100)])
    # A 连续 3 帧被挡，只看到 B
    for _ in range(3):
        tr.update([box(410, 100)])
    a = [t for t in tr.tracks if t.track_id == 1][0]
    assert a.time_since_update == 3 and a.state == "lost"
    # A 在预测位置附近重新出现，应复用 id=1
    tr.update([box(140, 100), box(420, 100)])
    a = [t for t in tr.tracks if t.track_id == 1][0]
    assert a.time_since_update == 0
    assert a.hits >= 2


def test_selector_does_not_switch_to_bigger_target():
    tr = IouTracker(iou_threshold=0.3, max_age=10, min_hits=1)
    sel = TargetSelector(reacquire_px=300, max_lost=10)
    tracks = tr.update([box(250, 100, 100, 200), box(0, 100, 80, 180)])
    d1 = sel.select(tracks, frame_center=(320, 240))
    assert d1 is not None and d1.marker_id == 1
    # 第二个目标变很大，但已锁定目标仍在，不能换
    tracks = tr.update([box(255, 100, 100, 200), box(0, 80, 300, 300)])
    d2 = sel.select(tracks, frame_center=(320, 240))
    assert d2 is not None and d2.marker_id == 1


class FakeBase:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def detect_all(self, frame):
        out = self.frames[self.i]
        self.i += 1
        return out


def test_tracking_detector_wrapper():
    frames = [
        [box(250, 100), box(0, 100, 80, 180)],
        [box(255, 100), box(0, 80, 300, 300)],
        [box(260, 100), box(0, 80, 300, 300)],
    ]
    import types

    cfg = types.SimpleNamespace(
        mot_iou_threshold=0.3, mot_max_age=10, mot_min_hits=1,
        mot_velocity_alpha=0.5, mot_reacquire_px=300, mot_max_lost=10,
    )
    det = TrackingDetector(FakeBase(frames), cfg)
    img = np.zeros((480, 640, 3), np.uint8)
    ids = []
    for _ in range(3):
        d = det.detect(img)
        ids.append(None if d is None else d.marker_id)
    assert ids == [1, 1, 1], ids


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[X ] {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
