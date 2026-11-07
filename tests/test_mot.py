# -*- coding: utf-8 -*-
"""MOT / 目标锁定回归测试（不接相机、不接飞控）。"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.mot import IouTracker, TargetSelector, TrackingDetector  # noqa: E402
from vnav.vision import Detection  # noqa: E402


def det(x1, y1, x2, y2, conf=0.9, appearance=None):
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
        appearance=appearance,
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


def test_selector_hides_predicted_detection():
    """丢失帧不能返回预测框，否则安全看门狗看不到丢目标。"""
    tr = IouTracker(iou_threshold=0.3, max_age=10, min_hits=1)
    sel = TargetSelector(reacquire_px=300, max_lost=10, allow_predict=False)
    tracks = tr.update([box(100, 100)])
    d = sel.select(tracks, frame_center=(320, 240))
    assert d is not None and d.marker_id == 1
    for _ in range(3):
        tracks = tr.update([])
        assert sel.select(tracks, frame_center=(320, 240)) is None
    # 重新出现，仍应恢复 id=1
    tracks = tr.update([box(130, 100)])
    d2 = sel.select(tracks, frame_center=(320, 240))
    assert d2 is not None and d2.marker_id == 1


def test_appearance_resolves_crossing():
    red = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    blue = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    tr = IouTracker(
        iou_threshold=0.3, max_age=10, min_hits=1,
        appearance_weight=0.5, appearance_min_sim=0.5,
    )
    tr.update([det(100, 100, 200, 300, appearance=red), det(180, 100, 280, 300, appearance=blue)])
    # 两人交叉：红往右、蓝往左，框都重叠；外观应把 ID 拉回正确的人
    tr.update([det(160, 100, 260, 300, appearance=red), det(120, 100, 220, 300, appearance=blue)])
    t1 = [t for t in tr.tracks if t.track_id == 1][0]
    t2 = [t for t in tr.tracks if t.track_id == 2][0]
    assert t1.bbox[0] > t2.bbox[0]  # 红(id1)在右，蓝(id2)在左


def test_selector_reacquires_by_appearance():
    red = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    blue = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    tr = IouTracker(
        iou_threshold=0.3, max_age=1, min_hits=1,
        appearance_weight=0.5, appearance_min_sim=0.5,
    )
    sel = TargetSelector(reacquire_px=300, max_lost=10, appearance_min_sim=0.5)
    tracks = tr.update([det(100, 100, 200, 300, appearance=red), det(400, 100, 500, 300, appearance=blue)])
    d = sel.select(tracks, frame_center=(150, 200))
    assert d is not None and d.marker_id == 1

    # 目标消失两帧，轨迹被删；蓝人还在
    tracks = tr.update([])
    assert sel.select(tracks, frame_center=(320, 240)) is None
    tracks = tr.update([det(150, 100, 250, 300, appearance=blue)])

    # 红人重新出现；蓝人离上次位置更近，但外观应选红
    tracks = tr.update([det(150, 100, 250, 300, appearance=blue), det(100, 100, 200, 300, appearance=red)])
    d2 = sel.select(tracks, frame_center=(320, 240))
    assert d2 is not None
    assert (d2.bbox[0] + d2.bbox[2]) / 2.0 < 200  # 红框中心 ~150


def test_lock_target_by_bbox():
    import types

    frames = [[box(100, 100), box(400, 100)]]
    cfg = types.SimpleNamespace(
        mot_iou_threshold=0.3, mot_max_age=10, mot_min_hits=1,
        mot_velocity_alpha=0.5, mot_reacquire_px=300, mot_max_lost=10,
        appearance_enabled=False, appearance_weight=0.5, appearance_min_sim=0.5,
    )
    det = TrackingDetector(FakeBase(frames), cfg)
    img = np.zeros((480, 640, 3), np.uint8)
    out = det.lock_target(img, (390, 90, 510, 310))
    assert out is not None
    assert (out.bbox[0] + out.bbox[2]) / 2.0 > 300


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
