# -*- coding: utf-8 -*-
"""取图源抽象：本地摄像头 / 网络视频流 / Gazebo 仿真相机。

为什么单独抽一层：
    原来 `VisionWorker` 里直接写死 `cv2.VideoCapture(cfg.camera_source)`，
    也就是说"取图"和"USB 摄像头"绑死了。可 SITL 的画面不在任何设备上，
    它是 Gazebo Transport 上的一个话题。要让同一套追踪代码既能跑实机又能
    跑仿真，就必须把"帧从哪来"这件事收成一个可替换的对象。

三个实现共用同一个接口，`VisionWorker` 只认这三件事：

    read()     -> (ok, frame_bgr)   没新帧时返回 (False, None)，不阻塞
    release()  -> None
    describe() -> 一句人话，用来打日志

注意 `read()` 在 Gazebo 实现里**永远不阻塞**：它只把最近收到的一帧交出去。
仿真画面是 30Hz 推过来的，主循环是 20Hz，两边不需要对齐——保留最新帧、
丢掉旧帧，正是控制循环想要的语义（要的是"现在看到什么"，不是"第几帧"）。
"""

import math
import shutil
import subprocess
import threading
import time

import numpy as np

try:
    import cv2
except ImportError as e:
    raise ImportError("需要 opencv-python：pip install opencv-python") from e


def is_gazebo_source(value):
    """判断配置里的 camera_source 是不是"走 Gazebo"。"""
    if not isinstance(value, str):
        return False
    return value == "gazebo" or value.startswith("gz:")


class LocalCamera:
    """本机摄像头或任意可被 OpenCV 打开的流（手机 IP Webcam、RTSP 等）。"""

    def __init__(self, source, width, height):
        self.source = source
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"打不开摄像头 {source!r}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()

    def describe(self):
        return f"本地/流 {self.source!r}"


class GazeboCamera:
    """从 Gazebo Transport 订阅相机图像。

    SITL 里 `gz_x500_mono_cam` 的相机话题形如：
        /world/<world>/model/x500_mono_cam_0/link/camera_link/sensor/camera/image
    话题名里的 world 和 model 实例名都会变，所以不给话题名时自动去
    `gz topic -l` 里找第一个 `/sensor/camera/image`。
    """

    def __init__(self, topic, width, height, timeout_s=10.0):
        try:
            import gz.transport13 as transport
            from gz.msgs10 import image_pb2
        except ImportError as e:
            raise RuntimeError(
                "这台机器没有 Gazebo 的 Python 绑定（gz.transport13）。"
                "SITL 取图必须在装了 Gazebo 的机器上跑（本项目是 WSL）。"
            ) from e

        self._transport = transport
        self._image_pb2 = image_pb2
        self.width = int(width)
        self.height = int(height)

        if not topic:
            topic = self._discover_topic()
        self.topic = topic

        self._lock = threading.Lock()
        self._frame = None
        self._stamp = 0.0
        self._count = 0

        self._node = transport.Node()
        ok = self._node.subscribe(image_pb2.Image, topic, self._on_image)
        if not ok:
            raise RuntimeError(f"订阅 Gazebo 相机话题失败：{topic}")

        # 等第一帧，避免启动瞬间"没目标"被误判成"丢目标"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None:
                    return
            time.sleep(0.05)
        raise RuntimeError(f"{timeout_s:.0f}s 内没收到图像：{topic}")

    # ---------------- 内部 ----------------

    @staticmethod
    def _discover_topic():
        if shutil.which("gz") is None:
            raise RuntimeError("找不到 gz 命令，无法自动发现相机话题，请显式指定")
        try:
            out = subprocess.run(
                ["gz", "topic", "-l"], capture_output=True, text=True, timeout=20
            )
        except Exception as e:
            raise RuntimeError(f"列 Gazebo 话题失败：{e}") from e
        cands = [
            t.strip()
            for t in out.stdout.splitlines()
            if t.strip().endswith("/image") and "/sensor/camera" in t
        ]
        if not cands:
            raise RuntimeError(
                "Gazebo 里没有相机话题。确认机型是 gz_x500_mono_cam，"
                "并且世界已经加载完（话题列表里应有 /world/.../sensor/camera/image）"
            )
        return cands[0]

    def _on_image(self, msg):
        frame = self._to_bgr(msg)
        if frame is None:
            return
        if (frame.shape[1], frame.shape[0]) != (self.width, self.height):
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        with self._lock:
            self._frame = frame
            self._stamp = time.monotonic()
            self._count += 1

    @staticmethod
    def _to_bgr(msg):
        """gz.msgs.Image -> numpy BGR。像素格式不同通道顺序不同，必须分开处理。"""
        w, h = int(msg.width), int(msg.height)
        if w <= 0 or h <= 0:
            return None
        raw = np.frombuffer(msg.data, dtype=np.uint8)
        fmt = int(msg.pixel_format_type)

        # gz.msgs.PixelFormatType: L_INT8=1, RGB_INT8=3, RGBA_INT8=4, BGR_INT8=5, BGRA_INT8=6
        if fmt == 3:  # RGB
            return raw.reshape(h, w, 3)[:, :, ::-1].copy()
        if fmt == 4:  # RGBA
            return raw.reshape(h, w, 4)[:, :, 2::-1].copy()
        if fmt == 5:  # BGR
            return raw.reshape(h, w, 3).copy()
        if fmt == 6:  # BGRA
            return raw.reshape(h, w, 4)[:, :, :3].copy()
        if fmt == 1:  # L_INT8 灰度
            return np.repeat(raw.reshape(h, w, 1), 3, axis=2)
        raise RuntimeError(f"没处理的像素格式 {fmt}")

    # ---------------- 对外接口 ----------------

    def read(self):
        with self._lock:
            frame = self._frame
        if frame is None:
            return False, None
        return True, frame

    def release(self):
        with self._lock:
            self._frame = None
        # 必须显式退订：否则 Node 析构时回调线程可能还在跑，
        # 解释器关闭阶段会直接 segfault（实测退出码 139）。
        try:
            self._node.unsubscribe(self.topic)
        except Exception:
            pass
        time.sleep(0.1)

    def describe(self):
        return f"Gazebo 话题 {self.topic}（{self.width}x{self.height}）"

    @property
    def frames(self):
        with self._lock:
            return self._count


def open_camera(cfg):
    """按配置返回取图源。

    cfg.camera_source 支持三种写法：
        0 / 1 / 2            本机摄像头序号
        "http://ip:8080/video"  网络视频流
        "gazebo"             自动找 Gazebo 相机话题（SITL）
        "gz:/world/.../image"  指定 Gazebo 话题
    """
    src = cfg.camera_source
    if is_gazebo_source(src):
        topic = "" if src == "gazebo" else str(src)[3:]
        return GazeboCamera(topic, cfg.frame_width, cfg.frame_height)
    return LocalCamera(src, cfg.frame_width, cfg.frame_height)


def gazebo_intrinsics(hfov_rad, native_width, frame_width):
    """由 Gazebo 相机的水平视场角算出等效内参。

    Gazebo 的 SDF 只给了 horizontal_fov 和图像宽高，没有直接给焦距；
    但针孔模型下 fx = (W/2) / tan(hfov/2)，是精确值（比标定还准）。
    缩放到实际使用的分辨率时按比例缩放即可。

    这也是仿真唯一的"作弊"之处：实机必须靠张正友标定拿到这个数。
    """
    fx_native = (native_width / 2.0) / math.tan(hfov_rad / 2.0)
    scale = float(frame_width) / float(native_width)
    fx = fx_native * scale
    return fx
