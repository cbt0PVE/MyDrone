# -*- coding: utf-8 -*-
"""检测器：把"画面里的目标"变成"机体坐标系下的位置"。

两种实现共用同一个输出（vision.Detection），下游的任务/安全/控制不用改：

    ArucoTracker  已知标签物理尺寸 + PnP  -> 精度高，需要标定，用于降落/对位
    YoloDetector  训练好的人体检测 + 单目测距 -> 精度一般，用于追踪

单目测距的公式（针孔模型）：

    深度 Z = fy * 目标真实高度 / 目标在画面里的像素高度

人高按 1.7m 算，实际 1.5~1.9m 就带来 ±12% 的距离误差，且误差随距离线性放大。
所以 YOLO 这条路只能支撑"保持距离跟随"，不能支撑"精确降落到人头顶"。
"""

import numpy as np

from .vision import Detection


def estimate_from_bbox(cx, cy, bbox_h_px, camera_matrix, real_height_m, mount="forward"):
    """由检测框中心与框高，估算目标在机体系下的位置。

    参数
    ----
    cx, cy : 框中心像素坐标
    bbox_h_px : 框的像素高度（用它反推深度）
    camera_matrix : 3x3 内参
    real_height_m : 目标真实高度（人约 1.7m）
    mount : "forward" 相机朝前 / "down" 相机朝下

    返回 (forward_m, right_m, down_m)，与 Aruco 的输出同一套约定。
    """
    fx = float(camera_matrix[0, 0])
    fy = float(camera_matrix[1, 1])
    cx0 = float(camera_matrix[0, 2])
    cy0 = float(camera_matrix[1, 2])

    if bbox_h_px <= 1.0:
        return None

    depth = fy * real_height_m / bbox_h_px  # 相机正前方距离
    x_cam = (cx - cx0) * depth / fx  # 画面横向 -> 相机 x（右）
    y_cam = (cy - cy0) * depth / fy  # 画面纵向 -> 相机 y（下）

    if mount == "down":
        # 相机朝下、画面顶部对机头：与 vision.camera_to_body 保持一致
        forward = -y_cam
        right = x_cam
        down = depth
    else:
        # 相机朝前：z 轴就是机头方向，y 轴向下与机体 z 同向
        forward = depth
        right = x_cam
        down = y_cam

    return float(forward), float(right), float(down)


class YoloDetector:
    """YOLO 检测器。支持 .pt 和 .onnx，带上 ByteTrack 的跟踪 ID。

    为什么用 track 而不是 predict：追踪任务需要"同一个人"的稳定 ID，
    否则画面里两个人交叉时目标会跳到另一个人身上。
    """

    def __init__(self, cfg, camera_matrix):
        self.cfg = cfg
        self.K = camera_matrix
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError("需要 ultralytics：pip install ultralytics") from e
        self._model = YOLO(self.cfg.yolo_weights)
        return self._model

    def detect(self, frame):
        if frame is None:
            return None
        model = self._load()

        # persist=True 让跟踪器在连续帧之间保持 ID
        results = model.track(
            frame,
            persist=True,
            conf=self.cfg.yolo_conf,
            classes=[self.cfg.target_class],
            verbose=False,
            tracker="bytetrack.yaml",
        )
        if not results:
            return None

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        # 取画面里最大的那个框（离得最近），作为主目标
        xyxy = boxes.xyxy.cpu().numpy()
        heights = xyxy[:, 3] - xyxy[:, 1]
        idx = int(np.argmax(heights))

        x1, y1, x2, y2 = xyxy[idx]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        h_px = float(y2 - y1)

        pose = estimate_from_bbox(
            cx, cy, h_px, self.K, self.cfg.person_height_m, self.cfg.camera_mount
        )
        if pose is None:
            return None
        forward, right, down = pose

        track_id = -1
        if boxes.id is not None:
            try:
                track_id = int(boxes.id[idx].item())
            except Exception:
                track_id = -1

        return Detection(
            marker_id=track_id,
            center_px=(float(cx), float(cy)),
            forward_m=forward,
            right_m=right,
            down_m=down,
            yaw_deg=0.0,
            tvec=np.array([right, down, forward], dtype=float),
        )


def build_detector(cfg, camera_matrix, dist_coeffs):
    """按配置返回检测器实例。两者都提供 .detect(frame) 接口。"""
    if cfg.detector == "aruco":
        from .vision import ArucoTracker

        return ArucoTracker(cfg, camera_matrix, dist_coeffs)

    return YoloDetector(cfg, camera_matrix)
