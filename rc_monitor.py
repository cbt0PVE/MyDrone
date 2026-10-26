#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读监视器：飞行模式 / 解锁状态 / RC 链路 / 电池。

不发控制指令，不解锁，不碰电机。用来确认拨开关时模式到底变没变。

用法:
    python rc_monitor.py            # 用下面 PORT
    python rc_monitor.py --port serial://COM7:57600

退出: Ctrl+C
"""

import argparse
import asyncio
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from mavsdk import System

# ================= 端口：改这一行 =================
# 数传电台通常是 57600："serial://COM5:57600"
# 飞控 USB 直连通常是 115200："serial://COM5:115200"
# 端口号看 设备管理器 -> 端口(COM 和 LPT)
PORT = "serial://COM6:115200"
# =================================================

T0 = time.time()

MODE_CN = {
    "OFFBOARD": "OFFBOARD  <- 代码控制",
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
}


def log(msg):
    print(f"[{time.time() - T0:6.2f}s] {msg}", flush=True)


def mode_text(mode):
    name = getattr(mode, "name", str(mode))
    return MODE_CN.get(name, name)


async def wait_connected(drone, timeout=15.0) -> bool:
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
            log(f"模式 -> {mode_text(mode)}")


async def watch_armed(drone, st):
    async for armed in drone.telemetry.armed():
        if armed != st.get("armed"):
            st["armed"] = armed
            log("ARMED 已解锁" if armed else "DISARMED 已上锁")


async def watch_rc(drone, st):
    async for rc in drone.telemetry.rc_status():
        if rc.available != st.get("rc"):
            st["rc"] = rc.available
            log("RC 链路有信号" if rc.available else "! RC 链路已断开")


async def watch_battery(drone, st):
    async for b in drone.telemetry.battery():
        v = round(b.voltage_v, 2)
        if abs(v - st.get("volt", -1)) > 0.1:
            st["volt"] = v
            log(f"电池 {v:.2f} V / {round(b.remaining_percent * 100)}%")


async def watch_status(drone, st):
    async for msg in drone.telemetry.status_text():
        log(f"[飞控] {msg.text}")


async def main(port) -> int:
    log(f"连接 {port} ...")
    drone = System()
    try:
        await asyncio.wait_for(drone.connect(system_address=port), 15)
    except Exception as e:
        log(f"[X] 打开端口失败: {e}")
        log("    改文件顶部的 PORT，或 --port 指定")
        return 1

    if not await wait_connected(drone):
        log("[X] 15 秒没有心跳。检查端口号 / 波特率（57600 或 115200）/ 飞控上电 / QGC 是否占用串口")
        return 1

    log("[OK] 已连接")
    log("")
    log("监视中。现在去拨遥控器开关，看有无『模式 ->』输出。Ctrl+C 退出。")
    log("")

    st = {}
    tasks = [
        asyncio.create_task(watch_mode(drone, st)),
        asyncio.create_task(watch_armed(drone, st)),
        asyncio.create_task(watch_rc(drone, st)),
        asyncio.create_task(watch_battery(drone, st)),
        asyncio.create_task(watch_status(drone, st)),
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
    ap.add_argument("--port", default=PORT, help=f"连接地址（默认 {PORT}）")
    args = ap.parse_args()

    try:
        sys.exit(asyncio.run(main(args.port)))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
