# -*- coding: utf-8 -*-
"""Offboard 下发层：把"机体速度"翻译成 PX4 的 NED 速度指令。

这一层只干三件事：
    1. 进入 Offboard 之前先把 setpoint 流跑起来（PX4 的硬性要求）
    2. 每轮把速度指令转成 NED 后发出去
    3. 退出时干净地交还控制权

所有异常都往上抛给任务层，由任务层决定"停住还是交还"。
"""

import asyncio

from mavsdk.offboard import OffboardError, VelocityNedYaw

from .vision import body_to_ned


class OffboardController:
    def __init__(self, drone, cfg, log=print):
        self.drone = drone
        self.cfg = cfg
        self.log = log
        self.started = False
        self.last_cmd = (0.0, 0.0, 0.0)

    async def start(self):
        """预热 setpoint 流，再切模式。

        为什么要预热：PX4 只有在收到 Offboard setpoint 之后才允许切入
        OFFBOARD。顺序反了会被直接拒绝（COMMAND_DENIED）。
        """
        period = 1.0 / self.cfg.control_hz
        self.log("预热 setpoint 流 ...")
        for _ in range(int(self.cfg.control_hz)):  # 约 1 秒
            await self.drone.offboard.set_velocity_ned(VelocityNedYaw(0, 0, 0, 0))
            await asyncio.sleep(period)

        self.log("请求切入 OFFBOARD ...")
        try:
            await asyncio.wait_for(self.drone.offboard.start(), 5)
        except (OffboardError, asyncio.TimeoutError) as e:
            raise RuntimeError(f"切入 Offboard 失败：{e}") from e
        self.started = True
        self.log("[OK] 已进入 OFFBOARD")

    async def send(self, v_forward, v_right, v_down, yaw_deg):
        """下发机体速度。yaw 用当前机头朝向，保证旋转后仍是同一个世界方向。"""
        vn, ve, vd = body_to_ned(v_forward, v_right, v_down, yaw_deg)
        self.last_cmd = (vn, ve, vd)
        await self.drone.offboard.set_velocity_ned(
            VelocityNedYaw(vn, ve, vd, yaw_deg)
        )

    async def hold(self, yaw_deg):
        """原地悬停：速度全零，但保持机头朝向。"""
        await self.send(0.0, 0.0, 0.0, yaw_deg)

    async def release(self):
        """交还控制权：先让 PX4 退出 Offboard，之后听遥控器的。"""
        if not self.started:
            return
        try:
            await asyncio.wait_for(self.drone.offboard.stop(), 3)
            self.log("已退出 OFFBOARD，控制权交还")
        except Exception as e:
            self.log(f"退出 Offboard 未确认：{e}")
        self.started = False

    async def land(self):
        """让 PX4 自己降落（它的下降比我们写的好）。"""
        self.log("请求 PX4 自主降落 ...")
        try:
            await asyncio.wait_for(self.drone.action.land(), 10)
            self.log("[OK] 已发送降落指令")
        except Exception as e:
            self.log(f"降落指令未确认：{e}")
