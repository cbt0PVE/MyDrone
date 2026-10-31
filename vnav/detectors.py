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


class OnnxDetector:
    """YOLOv8 的 ONNX 推理，只用 onnxruntime + OpenCV。

    为什么单独写一个而不是让 ultralytics 去读 .onnx：
        ultralytics 会把 torch 一起拖进来（CPU 版也几百 MB）。机载电脑
        （香橙派 5 Pro）上最终要转 RKNN，用不到 torch；WSL 仿真里更没必要。
        这套"letterbox -> 推理 -> 解码 -> NMS"的流程和上板前处理是一致的。

    与 YoloDetector 的差别：**没有 ByteTrack ID**（id 恒为 -1）。
        单目标场景（课程的三类场景都是单目标）不受影响；多目标交叉时
        需要换成带跟踪的实现。
    """

    NMS_IOU = 0.45

    def __init__(self, cfg, camera_matrix):
        self.cfg = cfg
        self.K = camera_matrix
        self._session = None
        self._input_name = None
        self._input_hw = None

    def _load(self):
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise ImportError(
                "要跑 .onnx 需要 onnxruntime：pip install onnxruntime"
            ) from e

        sess = ort.InferenceSession(
            str(self.cfg.yolo_weights), providers=["CPUExecutionProvider"]
        )
        inp = sess.get_inputs()[0]
        self._input_name = inp.name
        # 形如 [1, 3, 640, 640]；用模型自带的尺寸，不写死 640
        h, w = int(inp.shape[2]), int(inp.shape[3])
        self._input_hw = (h, w)
        self._session = sess
        return sess

    # ---------------- 前处理 ----------------

    def _letterbox(self, frame, new_hw):
        """等比缩放 + 灰边填充。返回 (blob, scale, pad_x, pad_y)。"""
        import cv2

        new_h, new_w = new_hw
        h, w = frame.shape[:2]
        scale = min(new_w / w, new_h / h)
        rw, rh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_LINEAR)

        canvas = np.full((new_h, new_w, 3), 114, dtype=np.uint8)
        pad_x, pad_y = (new_w - rw) // 2, (new_h - rh) // 2
        canvas[pad_y:pad_y + rh, pad_x:pad_x + rw] = resized

        blob = canvas[:, :, ::-1].astype(np.float32) / 255.0  # BGR->RGB, 归一化
        blob = np.transpose(blob, (2, 0, 1))[None]  # NCHW
        return blob, scale, pad_x, pad_y

    # ---------------- 后处理 ----------------

    @staticmethod
    def _decode(output, conf_thres, num_classes):
        """把 YOLOv8 输出解成 (boxes_xyxy, scores)。

        导出格式有两种，都要兼容：
            (1, 4+nc, 8400)  -> 转置后每行一个候选
            (1, 8400, 4+nc)
        单类模型的输出是 (1, 5, 8400)：4 个框参数 + 1 个类别分数。
        """
        pred = np.asarray(output)
        if pred.ndim == 3:
            pred = pred[0]
        if pred.shape[0] < pred.shape[1] and pred.shape[0] <= 4 + num_classes + 1:
            pred = pred.T  # (4+nc, N) -> (N, 4+nc)

        boxes_cxcywh = pred[:, :4]
        class_scores = pred[:, 4:]
        if class_scores.shape[1] == 0:
            return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

        best_cls = np.argmax(class_scores, axis=1)
        best_score = class_scores[np.arange(len(class_scores)), best_cls]
        keep = best_score >= conf_thres
        if not np.any(keep):
            return np.zeros((0, 4), np.float32), np.zeros((0,), np.float32)

        b = boxes_cxcywh[keep]
        s = best_score[keep]
        cx, cy, bw, bh = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
        xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
        return xyxy.astype(np.float32), s.astype(np.float32)

    # ---------------- 主流程 ----------------

    def detect(self, frame):
        if frame is None:
            return None
        import cv2

        sess = self._load()
        blob, scale, pad_x, pad_y = self._letterbox(frame, self._input_hw)
        outputs = sess.run(None, {self._input_name: blob})

        # 单类 person 模型：nc = 1
        num_classes = max(1, int(outputs[0].shape[1]) - 4) if outputs[0].ndim == 3 else 1
        xyxy, scores = self._decode(outputs[0], self.cfg.yolo_conf, num_classes)
        if len(xyxy) == 0:
            return None

        # 还原到原图坐标（去掉 padding、除以缩放比）
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - pad_x) / scale
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - pad_y) / scale
        xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, frame.shape[1] - 1)
        xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, frame.shape[0] - 1)

        # NMS：cv2 要的是 (x, y, w, h)
        rects = [[float(x2 - x1), float(y2 - y1), float(x1), float(y1)]
                 for x1, y1, x2, y2 in xyxy]
        idxs = cv2.dnn.NMSBoxes(rects, scores.tolist(), self.cfg.yolo_conf, self.NMS_IOU)
        if len(idxs) == 0:
            return None
        idxs = np.array(idxs).flatten().tolist()

        # 取最大的框（离得最近）当主目标，和 YoloDetector 的取舍一致
        heights = [rects[i][1] for i in idxs]
        pick = idxs[int(np.argmax(heights))]
        x1, y1, x2, y2 = xyxy[pick]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        h_px = float(y2 - y1)

        pose = estimate_from_bbox(
            cx, cy, h_px, self.K, self.cfg.person_height_m, self.cfg.camera_mount
        )
        if pose is None:
            return None
        forward, right, down = pose

        return Detection(
            marker_id=-1,  # 没有跟踪器，不给稳定 ID
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

    # .onnx 走纯 onnxruntime，不需要装 ultralytics/torch。
    # 这条路径和香橙派上板（ONNX -> RKNN）是同一套前处理，所以不是临时方案。
    if str(cfg.yolo_weights).lower().endswith(".onnx"):
        return OnnxDetector(cfg, camera_matrix)

    return YoloDetector(cfg, camera_matrix)
