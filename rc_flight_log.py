#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读飞行日志：不控飞机、不发 setpoint，遥控器手动飞，板子记录状态。

用途：周六验证基础飞行（前进/后退约 1m、转弯）时，记录模式、姿态、高度、
速度、RC、电池，事后看日志。

    python3 rc_flight_log.py --port serial:///dev/ttyACM0:115200
"""

import argparse
import asyncio
import signal
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from mavsdk import System

from vnav.flightlog import FlightLogger

STOP = False


def _sigint(signum, frame):
    global STOP
    STOP = True


async def main(port):
    global STOP
    signal.signal(signal.SIGINT, _sigint)

    fl = FlightLogger(log_dir="logs", prefix="manual_flight", state_hz=5.0)
    print(f"日志：{fl.text_path}")
    print(f"      {fl.jsonl_path}")

    drone = System()
    await drone.connect(system_address=port)
    async for s in drone.core.connection_state():
        if s.is_connected:
            break
    fl.event("link_connected", port=port)
    print("[OK] 已连接。只读模式：不会发 setpoint，不会控飞机。")
    print("现在用遥控器手动起飞、前进/后退、转弯、降落；Ctrl+C 结束记录。")

    st = {}

    async def watch_mode():
        async for m in drone.telemetry.flight_mode():
            st["mode"] = getattr(m, "name", str(m))

    async def watch_armed():
        async for a in drone.telemetry.armed():
            st["armed"] = bool(a)

    async def watch_pos():
        async for p in drone.telemetry.position():
            st["lat"] = p.latitude_deg
            st["lon"] = p.longitude_deg
            st["alt_rel"] = p.relative_altitude_m
            st["alt_abs"] = p.absolute_altitude_m

    async def watch_att():
        async for a in drone.telemetry.attitude_euler():
            st["roll"] = a.roll_deg
            st["pitch"] = a.pitch_deg
            st["yaw"] = a.yaw_deg

    async def watch_vel():
        async for v in drone.telemetry.velocity_ned():
            st["vn"] = v.north_m_s
            st["ve"] = v.east_m_s
            st["vd"] = v.down_m_s

    async def watch_bat():
        async for b in drone.telemetry.battery():
            st["volt"] = b.voltage_v
            st["batt_pct"] = b.remaining_percent

    async def watch_rc():
        async for r in drone.telemetry.rc_status():
            st["rc"] = bool(r.is_available)

    async def watch_status():
        async for msg in drone.telemetry.status_text():
            fl.event("fc_status", text=msg.text)

    tasks = [
        asyncio.create_task(watch_mode()),
        asyncio.create_task(watch_armed()),
        asyncio.create_task(watch_pos()),
        asyncio.create_task(watch_att()),
        asyncio.create_task(watch_vel()),
        asyncio.create_task(watch_bat()),
        asyncio.create_task(watch_rc()),
        asyncio.create_task(watch_status()),
    ]

    try:
        while not STOP:
            fl.state(
                mode=st.get("mode", "?"),
                armed=bool(st.get("armed")),
                alt_rel=round(float(st.get("alt_rel", 0.0)), 2),
                roll=round(float(st.get("roll", 0.0)), 1),
                pitch=round(float(st.get("pitch", 0.0)), 1),
                yaw=round(float(st.get("yaw", 0.0)), 1),
                vn=round(float(st.get("vn", 0.0)), 2),
                ve=round(float(st.get("ve", 0.0)), 2),
                vd=round(float(st.get("vd", 0.0)), 2),
                volt=round(float(st.get("volt", 0.0)), 2),
                batt_pct=round(float(st.get("batt_pct", -1.0)), 1),
                rc=bool(st.get("rc")),
            )
            await asyncio.sleep(0.1)
    finally:
        for t in tasks:
            t.cancel()
        fl.close()
        print("记录结束")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="只读手动飞行日志")
    ap.add_argument("--port", default="serial:///dev/ttyACM0:115200")
    asyncio.run(main(ap.parse_args().port))
