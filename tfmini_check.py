#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TFmini-S 接入自检：确认飞控真的读到了激光测距，并和气压计高度对比。

用法:
    python tfmini_check.py                    # 用下面的 PORT
    python tfmini_check.py --port serial://COM7:57600

它做什么:
    1. 读 MAVLink 的 DISTANCE_SENSOR（PX4 把 TFmini 数据转成这个消息）
    2. 同时读气压计相对高度
    3. 逐行对比，并在数值异常时给出提示

判读:
    有数据 + 随手动升降单调变化  -> 接线和参数都对了
    一直是 0 或 NaN             -> 驱动没起来（看 SENS_TFMINI_CFG 和接线）
    量程边缘跳变                -> 超过 12m 或太近，属于正常失效
    和气压计差 > 1m             -> 地面基准不同，或者激光打偏了（别对着反光/斜面）
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
# 飞控 USB 直连通常是 115200："serial://COM6:115200"
PORT = "serial://COM6:115200"
# =================================================

T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.2f}s] {msg}", flush=True)


async def wait_connected(drone, timeout=15.0):
    async def _wait():
        async for state in drone.core.connection_state():
            if state.is_connected:
                return True

    try:
        return await asyncio.wait_for(_wait(), timeout)
    except asyncio.TimeoutError:
        return False


async def watch_distance(drone, st):
    async for d in drone.telemetry.distance_sensor():
        st["dist"] = d.current_distance_m
        st["dmin"] = d.minimum_distance_m
        st["dmax"] = d.maximum_distance_m
        st["dist_t"] = time.monotonic()


async def watch_altitude(drone, st):
    async for pos in drone.telemetry.position():
        st["alt"] = pos.relative_altitude_m


async def watch_mode(drone, st):
    async for mode in drone.telemetry.flight_mode():
        st["mode"] = getattr(mode, "name", str(mode))


async def printer(st):
    last = 0.0
    valid = 0
    total = 0
    while True:
        await asyncio.sleep(0.5)
        now = time.monotonic()
        dist = st.get("dist")
        alt = st.get("alt")
        age = now - st.get("dist_t", 0)

        if dist is None or age > 2:
            text = "测距：还没有数据（DISTANCE_SENSOR 没收到）"
        else:
            total += 1
            dmin, dmax = st.get("dmin", 0), st.get("dmax", 0)
            in_range = dmin <= dist <= dmax if dmax else True
            if in_range:
                valid += 1
            flag = "" if in_range else "  <-- 超出量程，PX4 会判为无效"
            text = f"激光 {dist:5.2f} m（量程 {dmin:.2f}~{dmax:.2f}）{flag}"

            # 读数一直贴着量程下限 = 传感器被挡住/没打到地面，这是最常见的假数据
            if dmin and dist <= dmin + 0.02:
                st["low"] = st.get("low", 0) + 1
                if st["low"] == 10:
                    text += "  <-- 贴着量程下限：镜头被挡 / 朝向偏了 / 对着镜面或深色地面"
            else:
                st["low"] = 0

        if alt is not None:
            text += f" | 气压计 {alt:5.2f} m"
            if dist is not None and age <= 2 and abs(dist - alt) > 1.0:
                text += "  (两者差 >1m，见文件头说明)"

        if st.get("mode"):
            text += f" | 模式 {st['mode']}"

        if now - last > 0.5:
            last = now
            if total and total % 20 == 0:
                text += f"   [有效样本 {valid}/{total}]"
            log(text)


async def main(port) -> int:
    drone = System()
    log(f"连接 {port} ...")
    try:
        await asyncio.wait_for(drone.connect(system_address=port), 15)
    except Exception as e:
        log(f"[X] 打开端口失败：{e}")
        return 1

    if not await wait_connected(drone):
        log("[X] 15 秒没有心跳。检查端口 / 波特率 / QGC 是否占用串口")
        return 1

    # 固件版本很关键：PX4 1.15 之后取消了 EKF2_HGT_REF，高度源改为自动选择，
    # 参数建议完全不同，所以先把版本打出来。
    try:
        v = await asyncio.wait_for(drone.info.get_version(), 3)
        log(f"固件：PX4 {v.flight_sw_major}.{v.flight_sw_minor}.{v.flight_sw_patch} "
            f"git={v.flight_sw_git_hash[:8]}")
    except Exception:
        log("固件版本读取失败（不影响后续测距检查）")

    log("[OK] 已连接。现在用手在传感器下方上下移动，观察读数是否跟着变")
    log("")

    st = {}
    tasks = [
        asyncio.create_task(watch_distance(drone, st)),
        asyncio.create_task(watch_altitude(drone, st)),
        asyncio.create_task(watch_mode(drone, st)),
        asyncio.create_task(printer(st)),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="TFmini-S 接入自检")
    ap.add_argument("--port", default=PORT, help=f"连接地址（默认 {PORT}）")
    args = ap.parse_args()

    try:
        sys.exit(asyncio.run(main(args.port)))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
