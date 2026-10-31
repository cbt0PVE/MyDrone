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
    # 摄像头来源，三种写法：
    #   0 / 1 / 2        本机（或机载电脑）的摄像头序号
    #   "http://ip:8080/video"   手机装 IP Webcam 当无线摄像头用
    #   "gazebo"         SITL 仿真的相机（自动发现话题），见 docs/SITL_CAMERA.md
    # 没有机载电脑时，用手机当摄像头是最省钱的手持验证方案。
    camera_source: object = 0
    frame_width: int = 640
    frame_height: int = 480
    # 相机标定文件（可选）。没有就按画面尺寸估一个内参，测距会有偏差。
    calib_path: str = "calib.json"
    marker_size_m: float = 0.12  # ArUco 标签边长，实际拿尺子量
    aruco_dict: str = "DICT_4X4_50"
    show_window: bool = True  # 是否弹窗显示识别画面（机载电脑上关掉）

    # ---------------- SITL / Gazebo 相机 ----------------
    # 摘自 PX4 的 Tools/simulation/gz/models/mono_cam/model.sdf：
    #   horizontal_fov=1.74 rad（约 99.7°）、1280x960、30Hz
    # 仿真的内参是精确已知的，不需要标定——这正是它适合先验通链路的原因。
    gazebo_hfov_rad: float = 1.74
    gazebo_native_width: int = 1280
    gazebo_native_height: int = 960
    sitl_world: str = "mydrone_track"  # sim/worlds/ 里的世界名
    sitl_port: str = "udp://:14540"  # PX4 SITL 默认的 Onboard 端口

    # ---------------- 检测器选择 ----------------
    # "aruco" = 已知尺寸标签，PnP 精确解算（用于降落/标定）
    # "yolo"  = 训练好的人体检测，单目测距（用于追踪）
    detector: str = "yolo"
    yolo_weights: str = "runs/detect/runs/detect/coco_person/weights/best.pt"
    # 同一个模型的 ONNX 版本。后缀是 .onnx 时走 onnxruntime，不需要 torch。
    # SITL（WSL）默认用它；上香橙派也是这条路（ONNX -> RKNN）。
    yolo_weights_onnx: str = "runs/detect/runs/detect/coco_person/weights/best.onnx"
    yolo_conf: float = 0.35
    target_class: int = 0  # 单类模型里 person 就是 0
    # 相机安装方向：forward = 朝前（追人用），down = 朝下（降落用）
    camera_mount: str = "forward"

    # 单目测距用的先验尺寸：人有多高。按人群取平均，误差直接换算成距离误差。
    person_height_m: float = 1.70
    # 追踪时希望保持的距离（目标在画面里的大小对应这个距离）
    track_distance_m: float = 2.5
    kp_distance: float = 0.8  # 距离误差 -> 前后速度
    kp_center: float = 1.2  # 画面横向偏差 -> 左右速度

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


def apply_sitl_preset(cfg):
    """把配置切成"SITL 仿真"这一档。

    仿真和实机的差别只有三处，其余参数（PID、安全阈值、状态机）必须完全共用，
    否则仿真验证过的东西对实机没有意义：
        1. 取图源是 Gazebo 话题，不是摄像头
        2. 端口是 PX4 SITL 的 14540
        3. 没有 TFmini，高度会自动回退气压计（见 link.TelemetryState）
    """
    cfg.camera_source = "gazebo"
    cfg.port = cfg.sitl_port
    cfg.show_window = False
    # WSL 里没装 ultralytics/torch（几百 MB），仿真一律走 ONNX + onnxruntime。
    # 权重不存在就保持 .pt，让报错信息指向真正的问题。
    if os.path.exists(cfg.yolo_weights_onnx):
        cfg.yolo_weights = cfg.yolo_weights_onnx
    # 仿真里的人是已知模型（Fuel 的 MaleVisitorPhone），身高可由"已知距离 + bbox"
    # 反推出来：1.82m（2026-10-31 在 6.00m 处实测 bbox=164px、fx=539.9）。
    # 这样仿真里的测距误差只剩像素噪声（实测 +0.3%），不掺"人高先验"的误差。
    # 实机不能用这个值——真人 1.5~1.9m，先验误差是物理事实。
    cfg.person_height_m = 1.82
    return cfg


def load_camera_matrix(cfg: Config):
    """返回 (camera_matrix, dist_coeffs, 来源说明)。

    优先级：
        1. Gazebo 仿真 -> 由 horizontal_fov 精确算出（无畸变）
        2. calib.json -> 张正友标定结果
        3. 都没有     -> 估算，并明确告诉你测距不准

    calib.json 格式：
        {"camera_matrix": [fx,0,cx, 0,fy,cy, 0,0,1], "dist_coeffs": [k1,k2,p1,p2,k3]}
    """
    import numpy as np

    from .camera import gazebo_intrinsics, is_gazebo_source

    if is_gazebo_source(cfg.camera_source) and cfg.gazebo_native_width > 0:
        fx = gazebo_intrinsics(
            cfg.gazebo_hfov_rad, cfg.gazebo_native_width, cfg.frame_width
        )
        fy = fx  # Gazebo 相机是方形像素
        cx, cy = cfg.frame_width / 2.0, cfg.frame_height / 2.0
        k = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float64)
        d = np.zeros((5, 1), dtype=np.float64)
        note = (
            f"SITL 仿真内参 fx=fy={fx:.1f}（由 hfov={cfg.gazebo_hfov_rad} 算出，无畸变）"
        )
        return k, d, note

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
