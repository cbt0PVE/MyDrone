# -*- coding: utf-8 -*-
"""冒烟测试：不接无人机、不接摄像头也能跑。

用途：确认坐标变换、PID、ArUco 识别这三块基础逻辑没被改坏。
在 Mac 上装好 opencv 就能跑。

    python tests/test_vision_smoke.py
或
    python -m pytest tests/ -v
"""

import os
import sys

import numpy as np

# 让 tests/ 下的脚本能 import 到仓库根目录的 vnav
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.config import Config, load_camera_matrix  # noqa: E402
from vnav.detectors import estimate_from_bbox  # noqa: E402
from vnav.vision import (  # noqa: E402
    ArucoTracker,
    PID,
    body_to_ned,
    camera_to_body,
    ned_climb_rate,
)


def test_sitl_intrinsics():
    """SITL 相机内参必须由 hfov 精确算出：1280 宽 hfov=1.74 -> fx≈540，640 宽则减半。"""
    from vnav.camera import gazebo_intrinsics, is_gazebo_source

    assert abs(gazebo_intrinsics(1.74, 1280, 1280) - 539.9) < 0.2
    assert abs(gazebo_intrinsics(1.74, 1280, 640) - 269.97) < 0.2

    # 配置切到仿真后，load_camera_matrix 应走仿真分支、且不受 calib.json 影响
    cfg = Config()
    cfg.camera_source = "gazebo"
    cfg.frame_width, cfg.frame_height = 640, 480
    K, dist, note = load_camera_matrix(cfg)
    assert abs(K[0, 0] - 269.97) < 0.2
    assert abs(K[0, 2] - 320.0) < 1e-9 and abs(K[1, 2] - 240.0) < 1e-9
    assert np.allclose(dist, 0)  # 仿真无畸变
    assert "SITL" in note
    assert is_gazebo_source("gazebo") and is_gazebo_source("gz:/world/x/image")
    assert not is_gazebo_source(0) and not is_gazebo_source("http://1.2.3.4/video")


def test_altitude_sign():
    """高度符号回归测试：低于目标高度时必须给**负**的 NED 垂直速度（上升）。

    这条曾经写反过：SITL 里一上电就往地里压。台架/手持都发现不了。
    """
    # 低于目标 0.5m -> 要上升 -> vd < 0
    assert ned_climb_rate(+0.5, 0.4) < 0
    # 高于目标 0.5m -> 要下降 -> vd > 0
    assert ned_climb_rate(-0.5, 0.4) > 0
    # 正好在目标高度 -> 不动
    assert ned_climb_rate(0.0, 0.4) == 0.0
    # 限幅
    assert abs(ned_climb_rate(100.0, 0.4)) == 0.4
    assert abs(ned_climb_rate(-100.0, 0.4)) == 0.4


def test_body_to_ned():
    """机头朝北时，前进 1m/s 应该全部落在"北"上。"""
    vn, ve, vd = body_to_ned(1.0, 0.0, 0.0, yaw_deg=0.0)
    assert abs(vn - 1.0) < 1e-6 and abs(ve) < 1e-6 and abs(vd) < 1e-6

    # 机头朝东（yaw=90）时，前进 1m/s 应该全部落在"东"上
    vn, ve, vd = body_to_ned(1.0, 0.0, 0.0, yaw_deg=90.0)
    assert abs(vn) < 1e-6 and abs(ve - 1.0) < 1e-6

    # 机头朝北时，向右 1m/s 应该落在"东"上
    vn, ve, _ = body_to_ned(0.0, 1.0, 0.0, yaw_deg=0.0)
    assert abs(vn) < 1e-6 and abs(ve - 1.0) < 1e-6


def test_camera_to_body():
    """相机朝下、画面顶部对机头时的符号约定。

    注意方向：画面往下 = 机尾方向，所以 ty>0 时前向分量应为负。
    """
    # 标签偏画面下方（ty>0）-> 在机尾方向，前向分量为负
    forward, right, down = camera_to_body(np.array([0.0, 0.2, 2.0]))
    assert forward < 0 and abs(right) < 1e-9 and down > 0

    # 标签偏画面上方（ty<0）-> 在机头方向，前向分量为正
    forward, _, _ = camera_to_body(np.array([0.0, -0.2, 2.0]))
    assert forward > 0

    # 标签在画面偏右（tx>0）-> 应该落在机体右侧
    forward, right, _ = camera_to_body(np.array([0.3, 0.0, 2.0]))
    assert right > 0 and abs(forward) < 1e-9


def test_pid_basic():
    """纯比例项时输出应等于误差（未超限、无死区）。"""
    pid = PID(kp=1.0, ki=0.0, kd=0.0, out_limit=1.0, deadband=0.0)
    assert abs(pid.update(0.5, 0.05) - 0.5) < 1e-9

    # 输出要被限幅
    pid2 = PID(kp=10.0, ki=0.0, kd=0.0, out_limit=0.6, deadband=0.0)
    assert abs(pid2.update(1.0, 0.05) - 0.6) < 1e-9

    # 死区内不动作
    pid3 = PID(kp=1.0, ki=0.0, kd=0.0, out_limit=1.0, deadband=0.1)
    assert pid3.update(0.05, 0.05) == 0.0


def test_estimate_from_bbox():
    """单目测距：深度 = fy * 真实高度 / 框高，横向偏差按相似三角形换算。"""
    K = np.array([[500, 0, 320], [0, 500, 240], [0, 0, 1]], dtype=float)

    fwd, right, down = estimate_from_bbox(320, 240, 250, K, 1.7, mount="forward")
    assert abs(fwd - 3.4) < 1e-6
    assert abs(right) < 1e-6 and abs(down) < 1e-6

    _, right, _ = estimate_from_bbox(370, 240, 250, K, 1.7, mount="forward")
    assert abs(right - 0.34) < 1e-6

    fwd, _, down = estimate_from_bbox(320, 290, 250, K, 1.7, mount="down")
    assert abs(down - 3.4) < 1e-6
    assert abs(fwd + 50 * 3.4 / 500) < 1e-6


def test_aruco_detect_synthetic():
    """用 OpenCV 自己生成一张标签图，走完"识别 -> PnP -> 机体坐标"。"""
    import cv2

    cfg = Config()
    cfg.marker_size_m = 0.12
    K, dist, _ = load_camera_matrix(cfg)

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cfg.aruco_dict))
    marker = cv2.aruco.generateImageMarker(dictionary, 7, 240)

    canvas = np.full((480, 640), 255, np.uint8)
    canvas[120:360, 200:440] = marker  # 贴在画面正中
    frame = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    tracker = ArucoTracker(cfg, K, dist)
    det = tracker.detect(frame)

    assert det is not None, "合成图没识别到标签"
    assert det.marker_id == 7
    # 标签在画面正中 -> 前后左右都该接近 0
    assert abs(det.forward_m) < 1e-3
    assert abs(det.right_m) < 1e-3
    assert det.down_m > 0.05, "距离应为正值（标签在相机前方）"


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
