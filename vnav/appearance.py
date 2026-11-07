# -*- coding: utf-8 -*-
"""轻量外观描述子：HSV 颜色直方图。

用途：MOT 在 IoU 关联之外增加“像不像同一个人”的约束，解决两人交叉后
IoU 相近、仅靠位置会认错的问题。它不是完整 ReID，只是第一版；
以后可以替换成 OSNet/MobileNet 的 embedding，接口不变（都是归一化向量 + 相似度）。
"""

import cv2
import numpy as np


def histogram(frame, bbox, bins=(16, 8)):
    """取 bbox 中间区域（避开背景/脚），返回 L1 归一化的 HSV 2D 直方图。"""
    if frame is None or bbox is None:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
    y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
    if x2 - x1 < 8 or y2 - y1 < 16:
        return None

    # 中间 60% 宽、上 75% 高：衣服/头肩，避开脚和两侧背景
    cw, ch = x2 - x1, y2 - y1
    cx1 = x1 + int(cw * 0.2)
    cx2 = x1 + int(cw * 0.8)
    cy1 = y1 + int(ch * 0.1)
    cy2 = y1 + int(ch * 0.85)
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, list(bins), [0, 180, 0, 256])
    hist = hist.astype(np.float32).flatten()
    s = float(hist.sum())
    if s <= 0:
        return None
    return hist / s


def similarity(a, b):
    """两个直方图的相似度，0–1；任一为空返回 0。"""
    if a is None or b is None or len(a) != len(b):
        return 0.0
    # compareHist 的 correlation 范围 [-1,1]，截到 [0,1]
    v = float(cv2.compareHist(a.reshape(-1, 1), b.reshape(-1, 1), cv2.HISTCMP_CORREL))
    return max(0.0, min(1.0, v))
