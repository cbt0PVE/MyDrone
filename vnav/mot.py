# -*- coding: utf-8 -*-
"""多目标跟踪 + 目标锁定（MOT）。

为什么需要：
    检测器每帧只给“最大的框”时，画面里第二个人、短暂遮挡、目标交叉都会让
    主目标跳到别人身上。课程要求“部分遮挡”，长期目标是“人群中锁定特定的人”，
    所以中间必须有一层 MOT。

这一版做什么：
    - 用 IoU 做帧间关联（贪心匹配，够用且不引入额外依赖）；
    - 恒定速度预测，短暂丢失时 bbox 继续外推（coast）；
    - 轨迹状态 tentative/confirmed/lost，连续命中才确认；
    - TargetSelector 锁定一个 track_id，别的目标再大也不换；
    - 目标丢失后按“预测中心距离”重捕获，超时再放弃。

没做什么：
    - 外观 ReID（颜色直方图/OSNet）——接口留好，后续替换；
    - 相机运动补偿——MOT 在图像坐标系，机体运动会让 bbox 整体平移，
      实机上需要把速度/姿态补偿进来，见 docs/TRACKING_ALGO_PLAN.md。
"""

from dataclasses import dataclass, field, replace
import math

import numpy as np

from .appearance import histogram, similarity
from .vision import Detection


def _bbox_iou(a, b):
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    bb = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    return inter / max(1e-9, aa + bb - inter)


def _iou_matrix(tracks, dets):
    m = np.zeros((len(tracks), len(dets)), dtype=np.float32)
    for i, t in enumerate(tracks):
        for j, d in enumerate(dets):
            m[i, j] = _bbox_iou(t.bbox, d.bbox)
    return m


def _appearance_matrix(tracks, dets):
    m = np.zeros((len(tracks), len(dets)), dtype=np.float32)
    for i, t in enumerate(tracks):
        gallery = t.appearance_gallery or ([t.appearance] if t.appearance is not None else [])
        for j, d in enumerate(dets):
            if d.appearance is None or not gallery:
                continue
            m[i, j] = max(similarity(g, d.appearance) for g in gallery)
    return m


def _center(bbox):
    return np.array([(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0], dtype=np.float32)


@dataclass
class Track:
    track_id: int
    det: Detection
    bbox: np.ndarray
    score: float
    hits: int = 1
    time_since_update: int = 0
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    state: str = "tentative"  # tentative / confirmed / lost
    appearance: np.ndarray = None  # 最近一次归一化 HSV 直方图
    appearance_gallery: list = field(default_factory=list)  # 多帧模板，抗姿态/光照

    def add_appearance(self, hist, max_len=5):
        if hist is None:
            return
        self.appearance_gallery.append(hist)
        if len(self.appearance_gallery) > max_len:
            self.appearance_gallery = self.appearance_gallery[-max_len:]
        # 用 gallery 均值作为主模板，同时保留多模板用于 max 相似度
        mean = np.mean(self.appearance_gallery, axis=0)
        s = float(mean.sum())
        if s > 0:
            self.appearance = mean / s

    @property
    def confirmed(self):
        return self.state == "confirmed"


class IouTracker:
    """极简 IoU 关联跟踪器，不依赖 scipy/ByteTrack。"""

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_age: int = 15,
        min_hits: int = 3,
        velocity_alpha: float = 0.5,
        appearance_weight: float = 0.5,
        appearance_min_sim: float = 0.5,
        reacquire_px: float = 200.0,
    ):
        self.iou_threshold = float(iou_threshold)
        self.max_age = int(max_age)
        self.min_hits = max(1, int(min_hits))
        self.velocity_alpha = float(velocity_alpha)
        self.appearance_weight = float(appearance_weight)
        self.appearance_min_sim = float(appearance_min_sim)
        self.reacquire_px = float(reacquire_px)
        self.tracks = []
        self._next_id = 1

    def reset(self):
        self.tracks = []
        self._next_id = 1

    def update(self, detections):
        dets = [d for d in detections if d is not None and d.bbox is not None]
        # 1. 先按上一帧速度外推，短暂遮挡时 bbox 不会停在原地
        for t in self.tracks:
            t.bbox = t.bbox + np.array([t.velocity[0], t.velocity[1], t.velocity[0], t.velocity[1]])

        # 2. 贪心匹配：IoU + 外观相似度，两边都没用过才配
        iou = _iou_matrix(self.tracks, dets) if self.tracks and dets else np.zeros((len(self.tracks), len(dets)))
        sim = _appearance_matrix(self.tracks, dets) if self.tracks and dets else np.zeros((len(self.tracks), len(dets)))
        pairs = []
        for i in range(iou.shape[0]):
            for j in range(iou.shape[1]):
                # 正常靠 IoU；交叉时 IoU 可能低，但外观很像也允许关联
                if iou[i, j] >= self.iou_threshold or (
                    sim[i, j] >= self.appearance_min_sim and iou[i, j] >= 0.05
                ):
                    score = float(iou[i, j]) + self.appearance_weight * float(sim[i, j])
                    pairs.append((score, i, j))
        pairs.sort(reverse=True)

        used_t, used_d = set(), set()
        for _, i, j in pairs:
            if i in used_t or j in used_d:
                continue
            used_t.add(i)
            used_d.add(j)
            self._update_track(self.tracks[i], dets[j])

        # 3. 没匹配上的轨迹：lost，超过 max_age 删除
        alive = []
        for i, t in enumerate(self.tracks):
            if i not in used_t:
                t.time_since_update += 1
                t.state = "lost"
            if t.time_since_update <= self.max_age:
                alive.append(t)
        self.tracks = alive

        # 4. 没匹配上的检测：新轨迹
        for j, d in enumerate(dets):
            if j in used_d:
                continue
            self.tracks.append(
                Track(
                    track_id=self._next_id,
                    det=d,
                    bbox=np.asarray(d.bbox, dtype=np.float32).copy(),
                    score=float(d.confidence),
                    appearance=d.appearance,
                )
            )
            self._next_id += 1

        for t in self.tracks:
            # 只给“本帧有匹配”的轨迹升 confirmed；刚丢的不能又被抬回 confirmed
            if t.time_since_update == 0 and t.hits >= self.min_hits:
                t.state = "confirmed"
        return self.tracks

    def _update_track(self, track, det):
        old_c = _center(track.bbox)
        new_bbox = np.asarray(det.bbox, dtype=np.float32).copy()
        new_c = _center(new_bbox)
        delta = new_c - old_c
        a = self.velocity_alpha
        track.velocity = (1.0 - a) * track.velocity + a * delta
        track.bbox = new_bbox
        track.det = det
        track.score = float(det.confidence)
        if det.appearance is not None:
            if track.appearance is None:
                track.appearance = det.appearance
            else:
                # 慢更新，避免一帧遮挡/光照变化把模板带偏
                track.appearance = 0.8 * track.appearance + 0.2 * det.appearance
                s = float(track.appearance.sum())
                if s > 0:
                    track.appearance = track.appearance / s
        track.hits += 1
        track.time_since_update = 0
        track.state = "confirmed" if track.hits >= self.min_hits else "tentative"


class TargetSelector:
    """锁定一个 track_id；别的目标再大也不换。"""

    def __init__(
        self,
        reacquire_px: float = 200.0,
        max_lost: int = 30,
        allow_predict: bool = False,
        appearance_min_sim: float = 0.5,
    ):
        self.reacquire_px = float(reacquire_px)
        self.max_lost = int(max_lost)
        # 默认不在“丢失帧”返回预测框：安全看门狗必须看到真实的 detect 缺失。
        # 只保留轨迹用于重捕获；需要做纯视觉演示时才允许预测。
        self.allow_predict = bool(allow_predict)
        self.appearance_min_sim = float(appearance_min_sim)
        self.lock_id = None
        self.last_center = None
        self.lost_frames = 0
        self.locked_appearance = None

    def reset(self):
        self.lock_id = None
        self.last_center = None
        self.lost_frames = 0
        self.locked_appearance = None

    def lock(self, track_id, appearance=None):
        """外部指定要跟的人（未来 UI 点选/框选入口）。"""
        self.lock_id = int(track_id)
        self.locked_appearance = appearance
        self.lost_frames = 0
        self.last_center = None

    def select(self, tracks, frame_center=None):
        by_id = {t.track_id: t for t in tracks}

        # 已锁定：只要还在，就继续
        if self.lock_id is not None and self.lock_id in by_id:
            t = by_id[self.lock_id]
            if t.time_since_update > 0:
                self.lost_frames += 1
                self.last_center = _center(t.bbox)
                if not self.allow_predict:
                    # 关键：不要把预测框伪装成真实检测，否则 SafetyMonitor 不会 hold/释放。
                    return None
            else:
                self.lost_frames = 0
                self.last_center = _center(t.bbox)
                self._remember(t)
            return self._to_detection(t)

        # 锁定目标丢了：优先按外观重捕获，其次按预测中心距离
        if self.lock_id is not None:
            self.lost_frames += 1
            if self.lost_frames <= self.max_lost and self.last_center is not None:
                candidates = [t for t in tracks if t.confirmed]
                if candidates:
                    best = None
                    if self.locked_appearance is not None:
                        scored = []
                        for t in candidates:
                            dist = float(np.linalg.norm(_center(t.bbox) - self.last_center))
                            if dist > self.reacquire_px:
                                continue
                            s = similarity(self.locked_appearance, t.appearance)
                            scored.append((s, t))
                        if scored:
                            s, t = max(scored, key=lambda x: x[0])
                            if s >= self.appearance_min_sim:
                                best = t
                    if best is None and self.locked_appearance is None:
                        # 没有外观模板（或都不像）才退回距离最近
                        near = min(
                            candidates,
                            key=lambda t: float(np.linalg.norm(_center(t.bbox) - self.last_center)),
                        )
                        if float(np.linalg.norm(_center(near.bbox) - self.last_center)) <= self.reacquire_px:
                            best = near
                    if best is not None:
                        self.lock_id = best.track_id
                        self._remember(best)
                        return self._to_detection(best)
            if self.lost_frames > self.max_lost:
                self.reset()
            return None

        # 首次锁定：优先 confirmed；画面中心优先，其次面积大
        candidates = [t for t in tracks if t.confirmed]
        if not candidates:
            candidates = tracks
        if not candidates:
            return None
        if frame_center is not None:
            fc = np.asarray(frame_center, dtype=np.float32)
            best = min(candidates, key=lambda t: float(np.linalg.norm(_center(t.bbox) - fc)))
        else:
            best = max(candidates, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
        self.lock_id = best.track_id
        self.last_center = _center(best.bbox)
        self.lost_frames = 0
        self._remember(best)
        return self._to_detection(best)

    def _remember(self, track):
        if track.appearance is None:
            return
        if self.locked_appearance is None:
            self.locked_appearance = track.appearance
        else:
            self.locked_appearance = 0.8 * self.locked_appearance + 0.2 * track.appearance
            s = float(self.locked_appearance.sum())
            if s > 0:
                self.locked_appearance = self.locked_appearance / s

    @staticmethod
    def _to_detection(track):
        bbox = tuple(float(v) for v in track.bbox)
        return replace(track.det, marker_id=int(track.track_id), bbox=bbox)


class TrackingDetector:
    """把“检测器 + MOT + 目标锁定”包成和普通 detector 一样的 .detect(frame)。"""

    def __init__(self, base, cfg):
        self.base = base
        self.tracker = IouTracker(
            iou_threshold=getattr(cfg, "mot_iou_threshold", 0.3),
            max_age=getattr(cfg, "mot_max_age", 15),
            min_hits=getattr(cfg, "mot_min_hits", 3),
            velocity_alpha=getattr(cfg, "mot_velocity_alpha", 0.5),
            appearance_weight=getattr(cfg, "appearance_weight", 0.5),
            appearance_min_sim=getattr(cfg, "appearance_min_sim", 0.5),
        )
        self.selector = TargetSelector(
            reacquire_px=getattr(cfg, "mot_reacquire_px", 200.0),
            max_lost=getattr(cfg, "mot_max_lost", 30),
            allow_predict=getattr(cfg, "mot_allow_predict", False),
            appearance_min_sim=getattr(cfg, "appearance_min_sim", 0.5),
        )
        self.cfg = cfg
        self.use_appearance = bool(getattr(cfg, "appearance_enabled", True))
        self._pending_target_norm = None

    def set_pending_target_norm(self, bbox_norm):
        """起飞前点选结果：归一化 bbox，首帧转像素后锁定。"""
        if bbox_norm is None or len(bbox_norm) != 4:
            raise ValueError("bbox_norm 必须是 4 个数")
        vals = tuple(float(v) for v in bbox_norm)
        if not all(0.0 <= v <= 1.0 for v in vals):
            raise ValueError("bbox_norm 必须在 0–1")
        if vals[2] <= vals[0] or vals[3] <= vals[1]:
            raise ValueError("bbox_norm 的 x2/y2 必须大于 x1/y1")
        self._pending_target_norm = vals

    def detect(self, frame):
        if self._pending_target_norm is not None and frame is not None:
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = self._pending_target_norm
            bbox = (x1 * w, y1 * h, x2 * w, y2 * h)
            self._pending_target_norm = None
            out = self.lock_target(frame, bbox)
            if out is not None:
                return out

        dets = self.base.detect_all(frame)
        if self.use_appearance and frame is not None:
            for d in dets:
                d.appearance = histogram(frame, d.bbox)
        tracks = self.tracker.update(dets)
        h, w = frame.shape[:2]
        return self.selector.select(tracks, frame_center=(w / 2.0, h / 2.0))

    def detect_all(self, frame):
        return self.base.detect_all(frame)

    def lock_target(self, frame, bbox):
        """在给定帧里锁定与 bbox 重叠最大的目标，返回该目标 Detection。

        这是“人群中指定某个人”的程序入口；以后接 UI 时把用户框选的 bbox 传进来。
        """
        dets = self.base.detect_all(frame)
        if self.use_appearance and frame is not None:
            for d in dets:
                d.appearance = histogram(frame, d.bbox)
        tracks = self.tracker.update(dets)
        best = None
        best_iou = 0.0
        for t in tracks:
            i = _bbox_iou(bbox, t.bbox)
            if i > best_iou:
                best_iou = i
                best = t
        if best is None or best_iou <= 0.0:
            return None
        self.selector.lock(best.track_id, best.appearance)
        self.selector.last_center = _center(best.bbox)
        return self.selector.select(tracks, frame_center=_center(best.bbox))

    def reset(self):
        self.tracker.reset()
        self.selector.reset()
