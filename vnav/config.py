# -*- coding: utf-8 -*-
"""全部可调参数集中在这里。

改参数只改这个文件，不要去各个模块里翻。
每个参数都写了单位，没写单位的都是无量纲比例。
"""

import json
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # ---------------- 链路 ----------------
    # 数传：serial://COM5:57600    飞控 USB：serial://COM5:115200
    port: str = os.environ.get("DRONE_PORT", "serial://COM5:57600")
    connect_timeout_s: float = 15.0
    control_hz: float = 20.0  # 控制循环频率；PX4 要求 >2Hz，20Hz 留足余量

    # ---------------- 相机与标记 ----------------
    # 摄像头来源，两种写法都行：
    #   0 / 1 / 2        本机（或机载电脑）的摄像头序号
    #   "http://ip:8080/video"   手机装 IP Webcam 当无线摄像头用
    # 没有机载电脑时，用手机当摄像头是最省钱的手持验证方案。
    camera_source: object = 0
    frame_width: int = 640
    frame_height: int = 480
    # 相机标定文件（可选）。没有就按画面尺寸估一个内参，测距会有偏差。
    calib_path: str = "calib.json"
    marker_size_m: float = 0.12  # ArUco 标签边长，实际拿尺子量
    aruco_dict: str = "DICT_4X4_50"
    show_window: bool = True  # 是否弹窗显示识别画面（机载电脑上关掉）

    # ---------------- 飞行高度 ----------------
    hover_alt_m: float = 1.0  # 起飞后先爬到的高度
    descend_stop_alt_m: float = 0.35  # 降到这个高度就交给 PX4 自己落地
    descend_rate_mps: float = 0.25  # 下降速度（正数，内部取负）
    max_climb_mps: float = 0.4
    # 高度源：True = 优先用 TFmini 激光（离地高度），失效时自动回退气压计
    use_rangefinder: bool = True
    rangefinder_timeout_s: float = 1.0  # 激光数据超过这么久没更新就判为失效
    # 低于这个高度视为不可信（传感器被挡住/贴地时会钳在量程下限 0.10）
    rangefinder_min_valid_m: float = 0.15

    # ---------------- 对准判定 ----------------
    align_tolerance_m: float = 0.10  # 水平误差小于 10cm 算对正
    align_hold_s: float = 1.0  # 且要稳定保持 1 秒

    # ---------------- 视觉 PID（输出是速度 m/s） ----------------
    kp_xy: float = 0.8
    ki_xy: float = 0.05
    kd_xy: float = 0.15
    max_speed_mps: float = 0.6  # 水平速度上限
    deadband_m: float = 0.02  # 误差小于 2cm 不动，防抖

    # ---------------- 安全检查 ----------------
    target_stale_hold_s: float = 0.6  # 丢目标超过这个时间 -> 原地悬停
    target_stale_release_s: float = 2.0  # 再超过这个时间 -> 交还人工
    telemetry_stale_s: float = 1.0  # 遥测断流超过这个时间 -> 中止
    min_battery_pct: float = 0.20  # 电量低于 20% 不允许起飞
    min_start_alt_m: float = 0.5  # 进入视觉模式的最低高度

    def __post_init__(self):
        if self.control_hz <= 0:
            raise ValueError("control_hz 必须大于 0")


def parse_camera_source(value):
    """命令行传进来的字符串转成摄像头来源。

    "0" -> 0（本机摄像头序号）
    "http://..." -> 原样返回（视频流地址）
    """
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def load_camera_matrix(cfg: Config):
    """返回 (camera_matrix, dist_coeffs, 来源说明)。

    优先读 calib.json：
        {"camera_matrix": [fx,0,cx, 0,fy,cy, 0,0,1], "dist_coeffs": [k1,k2,p1,p2,k3]}
    读不到就用估算值，并明确告诉你测距不准。
    """
    import numpy as np

    if cfg.calib_path and os.path.exists(cfg.calib_path):
        try:
            with open(cfg.calib_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            k = np.array(data["camera_matrix"], dtype=np.float64).reshape(3, 3)
            d = np.array(data["dist_coeffs"], dtype=np.float64).reshape(-1, 1)
            return k, d, f"已加载标定文件 {cfg.calib_path}"
        except Exception as e:  # 文件坏了也不能崩，退化成估算
            reason = f"标定文件读取失败({e})"
    else:
        reason = "未找到标定文件"

    # 估算：焦距约为画面宽度的 0.9 倍，主点在画面中心
    fx = fy = 0.9 * cfg.frame_width
    cx, cy = cfg.frame_width / 2.0, cfg.frame_height / 2.0
    k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
    d = np.zeros((5, 1), dtype=np.float64)
    return k, d, f"{reason}，使用估算内参（距离仅供参考，需做张正友标定）"
