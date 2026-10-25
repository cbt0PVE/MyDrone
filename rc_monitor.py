#!/usr/bin/env python3
"""只读监视器：飞行模式 / 解锁状态 / RC 链路 / 电池。

不发送任何控制指令，不解锁，不碰电机。用来看拨开关时模式到底变没变。

用法:
    python rc_monitor.py                      # 默认端口
    python rc_monitor.py --port serial://COM6:57600
    set DRONE_PORT=serial://COM6:57600 && python rc_monitor.py   # Windows
    export DRONE_PORT=serial:///dev/tty.usbmodem1101              # macOS

退出: Ctrl+C
"""

import argparse
import asyncio
import os
import time
from datetime import datetime

from mavsdk import System
from mavsdk.telemetry import FlightMode

DEFAULT_PORT = os.environ.get("DRONE_PORT", "serial://COM5:57600")

# MAVSDK 的 FlightMode 枚举名（PX4 的定点是 POSCTL、定高是 ALTCTL）
MODE_CN = {
    "OFFBOARD": "OFFBOARD  ← 代码控制",
    "POSCTL": "POSCTL    定点",
    "ALTCTL": "ALTCTL    定高",
    "STABILIZED": "STABILIZED 自稳",
    "MANUAL": "MANUAL    手动",
    "ACRO": "ACRO      特技",
    "RATTITUDE": "RATTITUDE 增稳",
    "HOLD": "HOLD      悬停",
    "RETURN_TO_LAUNCH": "RTL       返航",
    "LAND": "LAND      降落",
    "TAKEOFF": "TAKEOFF   起飞中",
    "MISSION": "MISSION   任务",
    "READY": "READY     待命",
    "FOLLOW_ME": "FOLLOW_ME 跟随",
}

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.2f}s] {msg}", flush=True)


def mode_text(mode) -> str:
    name = getattr(mode, "name", str(mode))
    return MODE_CN.get(name, name)


async def wait_connected(drone, timeout=20.0) -> bool:
    async def _wait():
        async for state in drone.core.connection_state():
            if state.is_connected:
                return True

    try:
        return await asyncio.wait_for(_wait(), timeout)
    except asyncio.TimeoutError:
        return False


async def watch_mode(drone, st):
    async for mode in drone.telemetry.flight_mode():
        if mode != st.get("mode"):
            st["mode"] = mode
            log(f"模式 → {mode_text(mode)}")


async def watch_armed(drone, st):
    async for armed in drone.telemetry.armed():
        if armed != st.get("armed"):
            st["armed"] = armed
            log(f"{'🔓 已解锁 ARMED' if armed else '🔒 已上锁 DISARMED'}")


async def watch_rc(drone, st):
    async for rc in drone.telemetry.rc_status():
        avail = rc.available
        if avail != st.get("rc"):
            st["rc"] = avail
            log(f"RC 链路 {'有信号' if avail else '已断开'}")
        if avail:
            rssi = getattr(rc, "rssi", 0.0)
            if abs(rssi - st.get("rssi", -999)) > 10:
                st["rssi"] = rssi
                log(f"RC 信号强度 {rssi:.0f}%")


async def watch_battery(drone, st):
    async for b in drone.telemetry.battery():
        v, p = round(b.voltage_v, 2), round(b.remaining_percent * 100)
        if abs(v - st.get("volt", -1)) > 0.1:
            st["volt"] = v
            log(f"电池 {v:.2f} V / {p}%")


async def watch_status_text(drone, st):
    """飞控自己发的提示，预检失败原因通常在这里。"""
    async for msg in drone.telemetry.status_text():
        log(f"[飞控] {msg.text}")


async def main(port: str) -> int:
    drone = System()
    await drone.connect(system_address=port)

    log(f"等待心跳（{port}）…")
    if not await wait_connected(drone):
        log("✗ 20 秒内没收到心跳。检查：端口号 / 波特率 / 飞控是否上电")
        return 1

    log("✓ 通信建立")
    log("提示：现在去拨遥控器开关，观察下面是否有『模式 →』行")

    st: dict = {}
    tasks = [
        asyncio.create_task(watch_mode(drone, st)),
        asyncio.create_task(watch_armed(drone, st)),
        asyncio.create_task(watch_rc(drone, st)),
        asyncio.create_task(watch_battery(drone, st)),
        asyncio.create_task(watch_status_text(drone, st)),
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        log("监视结束")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="只读监视飞行模式 / RC 链路")
    ap.add_argument("--port", default=DEFAULT_PORT, help=f"MAVSDK 连接地址（默认 {DEFAULT_PORT}）")
    args = ap.parse_args()

    try:
        raise SystemExit(asyncio.run(main(args.port)))
    except KeyboardInterrupt:
        print("\n[!] 手动退出")
