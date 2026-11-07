# -*- coding: utf-8 -*-
"""目标时序滤波的回归测试。"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.tracker import TargetFilter  # noqa: E402
from vnav.vision import Detection  # noqa: E402


def det(forward, right=0.0, conf=0.9):
    return Detection(
        marker_id=1,
        center_px=(320.0, 240.0),
        forward_m=float(forward),
        right_m=float(right),
        down_m=0.2,
        yaw_deg=0.0,
        tvec=np.zeros(3, dtype=float),
        confidence=float(conf),
    )


def test_first_detection_passthrough():
    f = TargetFilter(alpha=0.5, max_jump_m=1.5, max_miss=3)
    d = det(2.0)
    assert f.update(d) is d
    assert f.target is d


def test_ema_smoothing():
    f = TargetFilter(alpha=0.5, max_jump_m=1.5, max_miss=3)
    f.update(det(1.0))
    out = f.update(det(2.0))
    assert abs(out.forward_m - 1.5) < 1e-6


def test_jump_hold_and_reset():
    f = TargetFilter(alpha=0.5, max_jump_m=1.0, max_miss=3)
    f.update(det(1.0))
    # 跳 5m，超过阈值：先保持旧值
    out = f.update(det(6.0))
    assert abs(out.forward_m - 1.0) < 1e-6
    # 连续异常 3 次后接受新目标
    f.update(det(6.0))
    out = f.update(det(6.0))
    assert abs(out.forward_m - 6.0) < 1e-6


def test_miss_resets():
    f = TargetFilter(alpha=0.5, max_jump_m=1.5, max_miss=3)
    f.update(det(1.0))
    assert f.update(None) is None
    assert f.update(None) is None
    f.update(None)
    assert f.target is None


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
