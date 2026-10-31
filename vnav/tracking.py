# -*- coding: utf-8 -*-
"""追踪任务：保持距离跟着目标，目标丢了就停住、丢久了就交还人工。

与降落任务的区别：
    降落：把目标对准到正下方，然后下降
    追踪：把目标保持在画面中心 + 保持固定距离（人/物体在前方，不是脚下）

相机朝前时，控制量是：
    前后速度  <- 距离误差（太远就前进，太近就后退）
    左右速度  <- 画面横向偏差（目标偏右就往右挪）
    升降速度  <- 用激光维持高度（与人同高，便于识别）
"""

import asyncio
import time
from enum import Enum

from .safety import Action


class Phase(Enum):
    SEARCH = "搜索目标"
    TRACK = "跟踪中"
    RELEASED = "已交还人工"
    DONE = "完成"


class TrackingMission:
    def __init__(self, state, vision, controller, cfg, safety, bench=False, log=print):
        self.state = state
        self.vision = vision
        self.controller = controller
        self.cfg = cfg
        self.safety = safety
        self.bench = bench
        self.log = log
        self.phase = Phase.SEARCH
        self._last_log = 0.0
        self._last_id = None

    async def run(self):
        cfg = self.cfg
        dt = 1.0 / cfg.control_hz

        try:
            while True:
                loop_start = time.monotonic()
                det, age = self.vision.latest()

                # ---- 1. 安全永远先判 ----
                action, reason = self.safety.evaluate(self.state, det, age)
                if action is Action.RELEASE:
                    self.log(f"!! 交还控制权：{reason}")
                    await self.controller.release()
                    self.phase = Phase.RELEASED
                    return
                if action is Action.ABORT:
                    self.log(f"!! 中止：{reason}")
                    await self.controller.land()
                    self.phase = Phase.DONE
                    return
                if action is Action.HOLD:
                    await self.controller.hold(self.state.yaw_deg)
                    self._log_throttled(f"暂时丢目标（{reason}），原地悬停")
                    await asyncio.sleep(max(0.0, dt - (time.monotonic() - loop_start)))
                    continue

                # ---- 2. 算速度 ----
                v_fwd, v_right, v_down = self._command(det)

                # ---- 3. 下发 ----
                await self.controller.send(v_fwd, v_right, v_down, self.state.yaw_deg)

                # ---- 4. 状态日志 ----
                self._log_status(det, age, v_fwd, v_right)

                await asyncio.sleep(max(0.0, dt - (time.monotonic() - loop_start)))

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log(f"!! 任务异常：{e}")
            try:
                await self.controller.hold(self.state.yaw_deg)
            except Exception:
                pass
            raise

    # ------------------------------------------------------------

    def _command(self, det):
        cfg = self.cfg

        # 高度保持：和目标大致同高，太高会看不到人
        if self.bench:
            v_down = 0.0
        else:
            err_alt = cfg.hover_alt_m - self.state.height_m
            v_down = max(-cfg.max_climb_mps, min(cfg.max_climb_mps, 0.8 * err_alt))

        if det is None:
            if self.phase is not Phase.SEARCH:
                self._enter(Phase.SEARCH)
            return 0.0, 0.0, v_down

        if self.phase is Phase.SEARCH:
            self._enter(Phase.TRACK)

        # 距离误差：太远给前进速度，太近给后退速度
        err_dist = det.forward_m - cfg.track_distance_m
        v_fwd = max(-cfg.max_speed_mps, min(cfg.max_speed_mps, cfg.kp_distance * err_dist))

        # 横向：目标偏右（right>0）就往右挪，把它拉回画面中心
        v_right = max(-cfg.max_speed_mps, min(cfg.max_speed_mps, cfg.kp_center * det.right_m))

        # 接近目标时降速，避免冲过头
        if abs(err_dist) < 0.5:
            v_fwd *= 0.5

        return v_fwd, v_right, v_down

    def _enter(self, phase):
        self.log(f"状态 {self.phase.value} -> {phase.value}")
        self.phase = phase

    # ------------------------------------------------------------

    def _log_status(self, det, age, v_fwd, v_right):
        now = time.monotonic()
        if now - self._last_log < 0.5:
            return
        self._last_log = now

        if det is None:
            target = "无目标"
        else:
            tid = det.marker_id
            target = (
                f"id={tid} 前{det.forward_m:+.2f} 右{det.right_m:+.2f} "
                f"下{det.down_m:.2f} (陈旧{age:.2f}s)"
            )
        self.log(
            f"[{self.phase.value}] 高 {self.state.height_m:4.2f}m({self.state.height_source}) | "
            f"{target} | 指令 前{v_fwd:+.2f} 右{v_right:+.2f} m/s"
        )

    def _log_throttled(self, msg):
        now = time.monotonic()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        self.log(msg)
