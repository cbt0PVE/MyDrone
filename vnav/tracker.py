# -*- coding: utf-8 -*-
"""目标时序滤波：把单帧检测值变成稳定的控制输入。

单目 YOLO 的框会随姿态、遮挡、量化抖动跳几厘米到几十厘米；直接拿
`det.forward_m/right_m` 做速度控制，指令会跟着抖。这里做两件事：

1. **EMA 平滑**：新值按 alpha 权重混入旧值，抑制高频抖动；
2. **跳变抑制**：一帧内目标位置跳超过 max_jump_m，先保持旧值；
   连续 max_miss 帧异常才接受新目标/重置（防止换人时瞬间拉过去）。

注意：它只平滑“控制用的目标”，不改变安全看门狗的判断——
`TrackingMission` 仍然把**原始检测**交给 `SafetyMonitor`，丢目标该悬停就悬停。
"""

from dataclasses import replace
import math

from .vision import Detection


class TargetFilter:
    def __init__(self, alpha: float = 0.35, max_jump_m: float = 1.5, max_miss: int = 5):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha 必须在 (0, 1]")
        self.alpha = float(alpha)
        self.max_jump_m = float(max_jump_m)
        self.max_miss = max(1, int(max_miss))
        self._det = None
        self._miss = 0

    def reset(self):
        self._det = None
        self._miss = 0

    @property
    def target(self):
        return self._det

    def update(self, det):
        """输入原始 Detection/None，返回平滑后的 Detection/None。

        原始为 None：累计丢失，超过 max_miss 后重置并返回 None。
        原始存在但跳变过大：先返回旧值（hold），连续异常才接受新值。
        """
        if det is None:
            self._miss += 1
            if self._miss >= self.max_miss:
                self.reset()
            return None

        if self._det is None:
            self._det = det
            self._miss = 0
            return det

        jump = math.hypot(
            det.forward_m - self._det.forward_m,
            det.right_m - self._det.right_m,
        )
        if jump > self.max_jump_m:
            self._miss += 1
            if self._miss >= self.max_miss:
                self._det = det
                self._miss = 0
                return det
            return self._det

        a = self.alpha
        cx = a * det.center_px[0] + (1.0 - a) * self._det.center_px[0]
        cy = a * det.center_px[1] + (1.0 - a) * self._det.center_px[1]
        smoothed = replace(
            det,
            center_px=(float(cx), float(cy)),
            forward_m=a * det.forward_m + (1.0 - a) * self._det.forward_m,
            right_m=a * det.right_m + (1.0 - a) * self._det.right_m,
            down_m=a * det.down_m + (1.0 - a) * self._det.down_m,
        )
        self._det = smoothed
        self._miss = 0
        return smoothed
