# -*- coding: utf-8 -*-
"""安全看门狗。

这是阶段四"安全防护机制"的核心：任何异常都必须收敛到"停住并交还人工"。

设计上把安全判定做成纯函数式的一步判断——输入当前状态，输出该做什么。
这样它不依赖飞控、不依赖相机，可以被单元测试，也方便课上讲清楚逻辑。

判定优先级（从高到低，命中即返回）：

    1. 遥测断流        -> ABORT   飞控都不说话了，什么都不用做
    2. 未解锁          -> ABORT   已经不在飞了
    3. 离开 OFFBOARD   -> RELEASE 遥控器抢权/拨了开关，立刻交还
    4. 电量过低        -> ABORT   尽快降落
    5. 丢目标太久      -> RELEASE 视觉不可靠，交还人工
    6. 短暂丢目标      -> HOLD    原地停住，等目标回来
    7. 其他            -> CONTINUE
"""

from enum import Enum


class Action(Enum):
    CONTINUE = "continue"  # 正常执行任务
    HOLD = "hold"  # 悬停不动（速度指令置零）
    RELEASE = "release"  # 放弃控制权（停止发指令 + 退出 Offboard）
    ABORT = "abort"  # 中止任务（通常随后降落）


class SafetyMonitor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.released = False  # 一旦交还人工，就不再收回控制权

    def evaluate(self, state, det, det_age):
        """返回 (Action, 原因字符串)。det 为 None 表示当前没有识别结果。"""
        cfg = self.cfg

        # 1. 遥测断流：飞控或链路已经不可信
        if state.telemetry_age > cfg.telemetry_stale_s:
            return Action.ABORT, f"遥测断流 {state.telemetry_age:.1f}s"

        # 2. 未解锁：任务没有继续的前提
        if not state.armed:
            return Action.ABORT, "飞行器未解锁"

        # 3. 离开 Offboard：遥控器抢权或拨了开关。
        #    这条必须在"丢目标"之前判断——人工接管优先级永远最高。
        if not state.offboard:
            self.released = True
            return Action.RELEASE, "已离开 OFFBOARD（人工接管）"

        # 4. 电量
        if state.battery_pct < cfg.min_battery_pct:
            return Action.ABORT, f"电量 {state.battery_pct*100:.0f}% 过低"

        # 5/6. 目标丢失分级处理
        if det is None or det_age > cfg.target_stale_release_s:
            self.released = True
            return Action.RELEASE, f"目标丢失 {det_age:.1f}s，超过交还阈值"
        if det_age > cfg.target_stale_hold_s:
            return Action.HOLD, f"目标短暂丢失 {det_age:.1f}s，原地悬停"

        return Action.CONTINUE, "正常"

    def check_ready(self, state, health=None, bench=False):
        """起飞前自检。返回问题列表，空列表表示可以开始。

        bench=True 是台架/手持验证：飞机不在空中，所以不检查高度。
        """
        cfg = self.cfg
        problems = []

        if state.telemetry_age > cfg.telemetry_stale_s:
            problems.append("遥测没有数据")
        if state.battery_pct < cfg.min_battery_pct:
            problems.append(f"电量 {state.battery_pct*100:.0f}% 低于 {cfg.min_battery_pct*100:.0f}%")
        if not state.armed:
            problems.append("未解锁（本任务要求先由飞手起飞并切 Offboard）")
        if not bench and state.alt_m < cfg.min_start_alt_m:
            problems.append(f"高度 {state.alt_m:.2f}m 低于 {cfg.min_start_alt_m}m，先由飞手起飞")

        if health is not None:
            if hasattr(health, "is_local_position_ok") and not health.is_local_position_ok:
                problems.append("没有本地位置估计（PX4 可能拒绝 Offboard）")
            if hasattr(health, "is_magnetometer_calibration_ok") and not health.is_magnetometer_calibration_ok:
                problems.append("磁罗盘未校准")
        return problems
