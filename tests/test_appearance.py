# -*- coding: utf-8 -*-
"""外观描述子（HSV 直方图）回归测试。"""

import os
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.appearance import histogram, similarity  # noqa: E402


def solid(color, size=100):
    img = np.zeros((size, size, 3), np.uint8)
    img[:, :] = color
    return img


def test_same_color_similar():
    a = histogram(solid((0, 0, 255)), (20, 20, 80, 80))
    b = histogram(solid((0, 0, 255)), (20, 20, 80, 80))
    assert a is not None and b is not None
    assert similarity(a, b) > 0.95


def test_different_color_dissimilar():
    a = histogram(solid((0, 0, 255)), (20, 20, 80, 80))  # 红
    b = histogram(solid((255, 0, 0)), (20, 20, 80, 80))  # 蓝
    assert similarity(a, b) < 0.5


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
