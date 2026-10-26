# -*- coding: utf-8 -*-
"""视觉：ArUco 检测 + PnP 位姿解算 + 视觉 PID + 后台取图线程。

三个坐标系必须先搞明白，否则正负号一定会写反：

1. 相机坐标系（OpenCV 约定）
       x 向右、y 向下、z 指向镜头正前方（射入画面）。
       相机装在机腹朝下时，z 轴就指向地面。

2. 机体坐标系 FRD（PX4 的机体系）
       x 向前（机头）、y 向右、z 向下。

3. 世界坐标系 NED
       x 向北、y 向东、z 向下。
       速度指令最终要转成 NED 下发给 PX4。

相机朝下、画面顶部对机头时，两者的对应关系是：

    机体前向  = -相机 y      （画面往下 = 机尾方向，取负才是机头）
    机体右向  =  相机 x
    机体下向  =  相机 z

这个映射写在 camera_to_body() 里。**装法不同就要改这里**，改完一定要做手持
验证：把飞机往左挪，看它是不是给出向右修正。方向反了就是这里错了。
"""

import threading
import time
from dataclasses import dataclass

import numpy as np

try:
    import cv2
except ImportError as e:  # 没装 OpenCV 时给出明确提示，而不是一堆堆栈
    raise ImportError("需要 opencv-python：pip install opencv-python") from e


# ====================================================================
# 检测结果
# ====================================================================


@dataclass
class Detection:
    """一次成功识别的结果。距离单位统一为米。"""

    marker_id: int
    center_px: tuple  # 画面上的像素坐标 (cx, cy)
    forward_m: float  # 标记在机体前向上的分量
    right_m: float  # 标记在机体右向上的分量
    down_m: float  # 标记在机体下向上的分量（也是相机到标签的直线距离）
    yaw_deg: float  # 标签相对相机的偏航角，用于对齐机头（可选）
    tvec: np.ndarray  # 原始平移向量，调试用


# ====================================================================
# 检测器
# ====================================================================


class ArucoTracker:
    """封装 OpenCV ArUco：检测角点 -> solvePnP -> 转成机体坐标。

    为什么用 PnP 而不是"像素面积估距离"：
    像素法受标签倾斜、透视影响极大；PnP 用已知标签物理尺寸和相机内参解出
    真实的 6DoF 位姿，倾斜时也准。代价是必须先做相机标定。
    """

    def __init__(self, cfg, camera_matrix, dist_coeffs):
        self.cfg = cfg
        self.K = camera_matrix
        self.dist = dist_coeffs

        # 字典与检测参数（新版 OpenCV 用 ArucoDetector 对象）
        if not hasattr(cv2.aruco, "getPredefinedDictionary"):
            raise RuntimeError("OpenCV 版本过旧，需要 4.6+ 才有 cv2.aruco")
        self.dictionary = cv2.aruco.getPredefinedDictionary(
            getattr(cv2.aruco, cfg.aruco_dict)
        )
        self.params = self._make_params()
        self.detector = self._make_detector()

        # 标签四个角在"标签坐标系"下的坐标，原点在标签中心、z 轴朝外。
        # 顺序必须与 detectMarkers 返回的角点顺序一致：
        # 左上 -> 右上 -> 右下 -> 左下（站在镜头视角看）。
        h = cfg.marker_size_m / 2.0
        self.object_points = np.array(
            [[-h, h, 0.0], [h, h, 0.0], [h, -h, 0.0], [-h, -h, 0.0]],
            dtype=np.float32,
        )

    # ---------------- 兼容不同 OpenCV 版本 ----------------

    def _make_params(self):
        params = cv2.aruco.DetectorParameters()
        # 机载相机画面小、抖动大，适当放宽阈值；精度优先时把这些调严
        params.adaptiveThreshWinSizeMin = 5
        params.adaptiveThreshWinSizeMax = 23
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        return params

    def _make_detector(self):
        if hasattr(cv2.aruco, "ArucoDetector"):  # OpenCV >= 4.7
            return cv2.aruco.ArucoDetector(self.dictionary, self.params)
        return None  # 老版本走 detectMarkers 函数

    # ---------------- 主入口 ----------------

    def detect(self, frame):
        """输入一帧 BGR 图像，返回 Detection 或 None。"""
        if frame is None:
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.detector is not None:
            corners, ids, _ = self.detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(
                gray, self.dictionary, parameters=self.params
            )

        if ids is None or len(corners) == 0:
            return None

        # 画面里可能有多个标签，取离画面中心最近的那个（追踪主目标）
        best = self._pick_nearest_center(corners, ids, frame.shape)
        corner = best[0].reshape(4, 2).astype(np.float64)

        # IPPE_SQUARE 是专门为平面方形标记优化的解法，比默认迭代法稳
        ok, rvec, tvec = cv2.solvePnP(
            self.object_points,
            corner,
            self.K,
            self.dist,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not ok:
            return None

        tvec = tvec.reshape(3)
        forward, right, down = camera_to_body(tvec)

        # 标签相对相机的偏航角：rvec 的第二列是标签 y 轴在相机系下的方向
        rmat, _ = cv2.Rodrigues(rvec)
        yaw = np.degrees(np.arctan2(rmat[0, 1], rmat[1, 1]))

        cx, cy = float(corner[:, 0].mean()), float(corner[:, 1].mean())
        return Detection(
            marker_id=int(best[1]),
            center_px=(cx, cy),
            forward_m=float(forward),
            right_m=float(right),
            down_m=float(down),
            yaw_deg=float(yaw),
            tvec=tvec,
        )

    @staticmethod
    def _pick_nearest_center(corners, ids, shape):
        """多个标签时，选离画面中心最近的那个。

        shape 是 frame.shape（高, 宽, 通道）。用画面中心而不是原点，
        因为机头正下方那个目标最可能就是我们想要的。
        """
        h, w = shape[0], shape[1]
        best, best_d = None, 1e9
        for corner, mid in zip(corners, ids.flatten()):
            pts = corner.reshape(4, 2)
            cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
            d = (cx - w / 2) ** 2 + (cy - h / 2) ** 2
            if d < best_d:
                best, best_d = (corner, int(mid)), d
        return best


# ====================================================================
# 坐标变换
# ====================================================================


def camera_to_body(tvec, signs=(1.0, -1.0, 1.0)):
    """相机系 -> 机体 FRD。

    tvec = (tx, ty, tz)：标签在相机系下的位置。
    signs 依次对应 (右, 前, 下) 三个方向的符号修正：
        forward = signs[1] * ty   （默认 -1：ty 越大说明标签越靠画面下方，
                                   也就是越靠机尾，取负才得到机头方向的前向分量）
        right   = signs[0] * tx
        down    = signs[2] * tz

    装法变了、或者手持验证发现方向相反，就改这里的 signs，
    不要在各个调用点分别取反（那样以后没人看得懂）。
    """
    forward = signs[1] * tvec[1]
    right = signs[0] * tvec[0]
    down = signs[2] * tvec[2]
    return forward, right, down


def body_to_ned(v_forward, v_right, v_down, yaw_deg):
    """机体速度 -> NED 速度。

    偏航角是机头相对正北的角度（顺时针为正）。把机体系投影到北东系：
        北 = cos(yaw)*前 - sin(yaw)*右
        东 = sin(yaw)*前 + cos(yaw)*右
        下 = 下
    如果不做这个旋转，飞机一转机头，修正方向就全乱了。
    """
    yaw = np.radians(yaw_deg)
    vn = np.cos(yaw) * v_forward - np.sin(yaw) * v_right
    ve = np.sin(yaw) * v_forward + np.cos(yaw) * v_right
    return float(vn), float(ve), float(v_down)


# ====================================================================
# PID
# ====================================================================


class PID:
    """带积分限幅与死区的离散 PID。

    为什么积分要限幅（抗饱和）：误差长时间不为零时积分项会越攒越大，
    等误差反向，积分还要花很久才能"还债"，表现为过冲和迟滞。
    无人机上这种迟滞很危险，所以把积分钳在一个小区间里。

    为什么微分用"误差变化率"而不是"测量值变化率"：
    量测噪声在求导后会被放大，直接用误差微分在视觉抖动下会让输出乱跳。
    这里加了低通（一阶滤波系数 alpha）来压噪。
    """

    def __init__(self, kp, ki, kd, out_limit, deadband=0.0, i_limit=None, alpha=0.3):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_limit = out_limit
        self.deadband = deadband
        self.i_limit = i_limit if i_limit is not None else out_limit
        self.alpha = alpha  # 微分低通系数，越小越平滑
        self.integral = 0.0
        self.prev_error = None
        self.d_filtered = 0.0

    def reset(self):
        self.integral = 0.0
        self.prev_error = None
        self.d_filtered = 0.0

    def update(self, error, dt):
        if dt <= 0:
            return 0.0

        # 死区：误差很小时不动作，避免在目标附近来回抽搐
        if abs(error) < self.deadband:
            error_for_p = 0.0
        else:
            error_for_p = error - np.sign(error) * self.deadband

        self.integral += error_for_p * dt
        self.integral = float(np.clip(self.integral, -self.i_limit, self.i_limit))

        if self.prev_error is None:
            derivative = 0.0
        else:
            derivative = (error - self.prev_error) / dt
        # 一阶低通，压住视觉噪声引起的微分毛刺
        self.d_filtered = (1 - self.alpha) * self.d_filtered + self.alpha * derivative
        self.prev_error = error

        out = self.kp * error_for_p + self.ki * self.integral + self.kd * self.d_filtered
        return float(np.clip(out, -self.out_limit, self.out_limit))


# ====================================================================
# 后台取图线程
# ====================================================================


class VisionWorker:
    """独立线程取图 + 识别，主控制循环只读"最新结果"。

    为什么不用协程直接做：cv2.VideoCapture.read() 是阻塞调用，放在事件循环里
    会卡住整个控制循环。控制循环必须稳定跑在 20Hz，所以把视觉放到线程里，
    两边只通过一个带锁的"最新结果"通信（只保留最新帧，旧帧直接丢）。
    """

    def __init__(self, cfg, tracker):
        self.cfg = cfg
        self.tracker = tracker
        self.cap = None
        self.thread = None
        self._running = False
        self._lock = threading.Lock()
        self._detection = None
        self._stamp = 0.0  # 最近一次成功识别的时间戳（time.monotonic）
        self._frame_count = 0

    # ---------------- 生命周期 ----------------

    def start(self):
        # camera_source 可以是序号（0/1）也可以是视频流地址（手机当摄像头）
        self.cap = cv2.VideoCapture(self.cfg.camera_source)
        if not self.cap.isOpened():
            raise RuntimeError(f"打不开摄像头 {self.cfg.camera_source!r}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.frame_height)

        self._running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self._running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
        if self.cfg.show_window:
            cv2.destroyAllWindows()

    # ---------------- 对外的读接口 ----------------

    def latest(self):
        """返回 (Detection 或 None, 距上次成功识别的秒数)。"""
        with self._lock:
            det = self._detection
            age = time.monotonic() - self._stamp if self._stamp else 1e9
        return det, age

    @property
    def frames(self):
        return self._frame_count

    # ---------------- 线程主体 ----------------

    def _loop(self):
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            self._frame_count += 1
            det = self.tracker.detect(frame)

            with self._lock:
                if det is not None:
                    self._detection = det
                    self._stamp = time.monotonic()
                # 识别不到时不清空上一次结果，而是让调用方根据 age 判断"陈旧"
                # ——这样短暂丢帧不会让控制量瞬间归零，动作更连贯。

            if self.cfg.show_window:
                self._draw(frame, det)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    self._running = False

    def _draw(self, frame, det):
        """画面上叠加识别结果，方便肉眼确认识别是否稳定。"""
        if det is not None:
            cx, cy = int(det.center_px[0]), int(det.center_px[1])
            cv2.drawMarker(frame, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
            text = f"id={det.marker_id} fwd={det.forward_m:+.2f} right={det.right_m:+.2f} d={det.down_m:.2f}m"
        else:
            text = "no marker"
        cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.imshow("vnav vision", frame)
