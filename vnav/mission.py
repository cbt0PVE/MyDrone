# -*- coding: utf-8 -*-
"""视觉追踪降落任务：一个显式状态机。

状态流转：

    SEARCH   等目标出现，保持当前高度悬停
      |  连续 N 帧识别到目标
      v
    ALIGN    水平对准标签正上方（XY 用视觉 PID）
      |  水平误差 < 容差 且稳定保持 align_hold_s
      v
    DESCEND  边对准边下降
      |  高度 <= descend_stop_alt_m
      v
    LANDING  交给 PX4 自主落地

任何时刻命中安全看门狗（丢目标/抢权/断链），直接跳到 RELEASED 或 ABORT。
"""

import asyncio
import time
from enum import Enum

from .safety import Action
from .vision import PID


class Phase(Enum):
    SEARCH = "搜索目标"
    ALIGN = "水平对准"
    DESCEND = "下降"
    LANDING = "落地"
    DONE = "完成"
    RELEASED = "已交还人工"


class VisualLandingMission:
    def __init__(self, state, vision, controller, cfg, safety, bench=False, log=print):
        self.state = state
        self.vision = vision
        self.controller = controller
        self.cfg = cfg
        self.safety = safety
        self.bench = bench  # 台架/手持模式：只对准、不下降
        self.log = log

        # 水平两个 PID 分别控制"前向"和"右向"速度。
        # 输入是米，输出是 m/s，所以增益的量纲是 1/s。
        self.pid_fwd = PID(
            cfg.kp_xy, cfg.ki_xy, cfg.kd_xy,
            out_limit=cfg.max_speed_mps, deadband=cfg.deadband_m,
            i_limit=0.3,
        )
        self.pid_right = PID(
            cfg.kp_xy, cfg.ki_xy, cfg.kd_xy,
            out_limit=cfg.max_speed_mps, deadband=cfg.deadband_m,
            i_limit=0.3,
        )

        self.phase = Phase.SEARCH
        self.align_since = None  # 开始满足对准条件的时间
        self.last_det = None
        self._land_sent = False
        self._last_log = 0.0

    # ------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------

    async def run(self):
        cfg = self.cfg
        dt = 1.0 / cfg.control_hz
        phase_since = time.monotonic()

        try:
            while True:
                loop_start = time.monotonic()
                det, age = self.vision.latest()

                # ---- 1. 安全判定永远先做 ----
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
                    # 目标短暂丢失：原地停住，等下一帧。不清 PID，免得重新找到
                    # 目标时从零开始积分，动作会突兀。
                    await self.controller.hold(self.state.yaw_deg)
                    self._log_throttled(f"暂时丢目标（{reason}），原地悬停")
                    await asyncio.sleep(max(0.0, dt - (time.monotonic() - loop_start)))
                    continue

                # ---- 2. 按状态机算期望速度 ----
                v_fwd, v_right, v_down = self._command(det, dt)

                # 到达降落高度后，最后一步交给 PX4 自己落地
                if self.phase is Phase.LANDING and not self._land_sent:
                    self._land_sent = True
                    await self.controller.land()
                    self.phase = Phase.DONE
                    return

                # ---- 3. 下发 ----
                await self.controller.send(v_fwd, v_right, v_down, self.state.yaw_deg)

                # ---- 4. 打印一行状态（限频，别刷屏）----
                self._log_status(det, age, v_fwd, v_right, v_down, phase_since)

                # ---- 5. 保持固定周期 ----
                elapsed = time.monotonic() - loop_start
                await asyncio.sleep(max(0.0, dt - elapsed))

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
    # 状态机
    # ------------------------------------------------------------

    def _command(self, det, dt):
        """根据当前阶段返回 (前向速度, 右向速度, 向下速度)。"""
        cfg = self.cfg
        alt = self.state.alt_m

        # 悬停高度保持：高度误差 -> 垂直速度（正数向上，所以取负号给 NED）
        # 台架/手持模式下飞控并没有真的在空中，绝不能给爬升指令，
        # 否则电机会一边被手托着一边拼命加油门。
        v_alt_hold = 0.0
        if not self.bench:
            v_alt_hold = max(
                -cfg.max_climb_mps,
                min(cfg.max_climb_mps, 0.8 * (cfg.hover_alt_m - alt)),
            )

        if self.phase is Phase.SEARCH:
            if det is not None:
                self._enter(Phase.ALIGN)
            return 0.0, 0.0, v_alt_hold

        if self.phase is Phase.ALIGN:
            v_fwd, v_right = self._center(det, dt)

            # 对准判定：误差小、且持续够久，才进入下降，防止"路过"中心就下潜
            ok = (
                abs(det.forward_m) < cfg.align_tolerance_m
                and abs(det.right_m) < cfg.align_tolerance_m
            )
            if ok:
                if self.align_since is None:
                    self.align_since = time.monotonic()
                elif time.monotonic() - self.align_since > cfg.align_hold_s:
                    if self.bench:
                        self._log_throttled("已对准（台架模式不下降）")
                    else:
                        self._enter(Phase.DESCEND)
            else:
                self.align_since = None
            return v_fwd, v_right, v_alt_hold

        if self.phase is Phase.DESCEND:
            v_fwd, v_right = self._center(det, dt)
            # NED 向下为正，所以下降速度取正数
            v_down = cfg.descend_rate_mps

            if alt <= cfg.descend_stop_alt_m:
                self._enter(Phase.LANDING)
                return 0.0, 0.0, 0.0
            return v_fwd, v_right, v_down

        if self.phase is Phase.LANDING:
            # 具体降落动作在主循环里做（那里可以 await）
            return 0.0, 0.0, 0.0

        return 0.0, 0.0, 0.0

    def _center(self, det, dt):
        """用视觉 PID 把目标拉到机体正下方。

        误差就是标签在机体系下的水平偏移。偏移为正向哪边，就给哪边的速度，
        所以 P 项符号是正的——这也是手持验证要看的东西：飞机往左偏时，
        电机应该往右修正，说明符号对。
        """
        if det is None:
            return 0.0, 0.0
        v_fwd = self.pid_fwd.update(det.forward_m, dt)
        v_right = self.pid_right.update(det.right_m, dt)
        return v_fwd, v_right

    def _enter(self, phase):
        self.log(f"状态 {self.phase.value} -> {phase.value}")
        self.phase = phase
        self.align_since = None

    # ------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------

    def _log_status(self, det, age, v_fwd, v_right, v_down, phase_since):
        now = time.monotonic()
        if now - self._last_log < 0.5:
            return
        self._last_log = now

        if det is None:
            target = "无目标"
        else:
            target = (
                f"前{det.forward_m:+.2f} 右{det.right_m:+.2f} 下{det.down_m:.2f} "
                f"(陈旧{age:.2f}s)"
            )
        self.log(
            f"[{self.phase.value}] 高 {self.state.alt_m:4.2f}m | {target} | "
            f"指令 前{v_fwd:+.2f} 右{v_right:+.2f} 下{v_down:+.2f} m/s"
        )

    def _log_throttled(self, msg):
        now = time.monotonic()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        self.log(msg)
