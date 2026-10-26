# -*- coding: utf-8 -*-
"""链路：连接 PX4，并把遥测数据缓存成"随时可读"的状态对象。

为什么要缓存：MAVSDK 的遥测是异步生成器（async for），只能顺序消费。
但控制循环每一轮都需要"当前高度/姿态/模式"，所以后台开几个任务不停把
最新值写进 TelemetryState，控制循环只读快照。

还要记 last_update 时间戳：如果飞控突然断链，遥测就不再更新，
控制循环必须能发现"数据是旧的"，而不是拿着旧值继续飞。
"""

import asyncio
import time

from mavsdk import System
from mavsdk.telemetry import FlightMode


async def connect(port, timeout=15.0, log=print):
    """连接飞控并等到心跳。失败抛 RuntimeError，调用方负责提示。"""
    drone = System()
    log(f"连接 {port} ...")
    try:
        await asyncio.wait_for(drone.connect(system_address=port), timeout)
    except asyncio.TimeoutError:
        raise RuntimeError("打开端口超时：端口号/波特率/线缆")

    async def _wait():
        async for state in drone.core.connection_state():
            if state.is_connected:
                return

    try:
        await asyncio.wait_for(_wait(), timeout)
    except asyncio.TimeoutError:
        raise RuntimeError("收不到心跳：飞控没上电，或 QGC 占用了串口")

    log("[OK] 通信建立")
    return drone


async def read_health(drone, timeout=3.0):
    """读一次健康状态；读不到返回 None（老固件可能没有这个字段）。"""
    try:
        return await asyncio.wait_for(anext(drone.telemetry.health()), timeout)
    except Exception:
        return None


class TelemetryState:
    """飞控状态快照。所有字段都由后台任务持续刷新。"""

    def __init__(self):
        self.mode = None
        self.armed = False
        self.alt_m = 0.0
        self.yaw_deg = 0.0
        self.rc_available = False
        self.battery_pct = 1.0
        self.last_update = 0.0  # 最近一次收到任何遥测的 time.monotonic()
        self._tasks = []

    # ---------------- 生命周期 ----------------

    def start(self, drone):
        """启动后台刷新任务。返回自己的任务列表，方便统一取消。"""
        self._tasks = [
            asyncio.create_task(self._watch_mode(drone)),
            asyncio.create_task(self._watch_armed(drone)),
            asyncio.create_task(self._watch_position(drone)),
            asyncio.create_task(self._watch_attitude(drone)),
            asyncio.create_task(self._watch_rc(drone)),
            asyncio.create_task(self._watch_battery(drone)),
        ]
        return self._tasks

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    # ---------------- 派生属性 ----------------

    @property
    def telemetry_age(self):
        """距上次收到遥测的秒数。用来判断链路是否还活着。"""
        if not self.last_update:
            return 1e9
        return time.monotonic() - self.last_update

    @property
    def offboard(self):
        return self.mode == FlightMode.OFFBOARD

    # ---------------- 各个后台任务 ----------------

    async def _watch_mode(self, drone):
        async for mode in drone.telemetry.flight_mode():
            self.mode = mode
            self.last_update = time.monotonic()

    async def _watch_armed(self, drone):
        async for armed in drone.telemetry.armed():
            self.armed = armed
            self.last_update = time.monotonic()

    async def _watch_position(self, drone):
        async for pos in drone.telemetry.position():
            self.alt_m = pos.relative_altitude_m
            self.last_update = time.monotonic()

    async def _watch_attitude(self, drone):
        async for euler in drone.telemetry.attitude_euler():
            self.yaw_deg = euler.yaw_deg
            self.last_update = time.monotonic()

    async def _watch_rc(self, drone):
        async for rc in drone.telemetry.rc_status():
            self.rc_available = rc.available
            self.last_update = time.monotonic()

    async def _watch_battery(self, drone):
        async for b in drone.telemetry.battery():
            self.battery_pct = b.remaining_percent
            self.last_update = time.monotonic()


def describe_mode(state):
    """把枚举转成可读文本，日志里看得懂。"""
    if state.mode is None:
        return "未知"
    return getattr(state.mode, "name", str(state.mode))
