#!/usr/bin/env python3
"""联通 → 解锁 → 1 米悬停。Ctrl+C 或遥控器接管都会安全让出。

用法:
    python hover_test.py                    # 默认端口、1 米、悬停到 Ctrl+C
    python hover_test.py --alt 1.0 --hold 60
    python hover_test.py --no-arm           # 只发数据流，不解锁（先验证模式切换）

手托测试步骤:
    1. 先 --no-arm 跑一遍，确认能进 OFFBOARD、拨开关能切出来
    2. 装桨、站到侧面、双手托住机架（全程别松手）
    3. 正常运行本脚本，解锁后推力会升到 HOVER_THRUST
    4. 顺势把飞机托到 1 米左右，感受推力是否在自动回调
    5. Ctrl+C 或拨遥控器开关，脚本自动让出并降落

注意:
    - 高度靠气压计，手托时读数会漂，属正常
    - 推力被限制在 MIN_THRUST ~ MAX_THRUST 之间
    - 永不调用 kill()
"""

import argparse
import asyncio
import os
import sys
import time

from mavsdk import System
from mavsdk.offboard import Attitude, OffboardError
from mavsdk.telemetry import FlightMode

# ============ 预设值（按需改这里，或命令行传参） ============
PORT = os.environ.get("DRONE_PORT", "serial://COM5:57600")
TARGET_ALT = 1.0        # 目标高度 m
HOLD_SEC = 0.0          # 悬停多少秒后自动降落；0 = 一直悬停到 Ctrl+C
HOVER_THRUST = 0.35     # 悬停基准推力 0~1（250 级 4S 大概 0.35~0.45）
KP_ALT = 0.7            # 高度环增益
MIN_THRUST = 0.08
MAX_THRUST = 0.70       # 安全上限，别轻易调高

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:7.2f}s] {msg}", flush=True)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


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
            name = getattr(mode, "name", str(mode))
            log(f"模式 → {name}")
            if st.get("expect_offboard") and mode != FlightMode.OFFBOARD:
                st["handed_over"] = True


async def watch_armed(drone, st):
    async for armed in drone.telemetry.armed():
        if armed != st.get("armed"):
            st["armed"] = armed
            log("🔓 ARMED 已解锁" if armed else "🔒 DISARMED 已上锁")


async def watch_altitude(drone, st):
    async for pos in drone.telemetry.position():
        st["alt"] = pos.relative_altitude_m


async def watch_status(drone, st):
    async for msg in drone.telemetry.status_text():
        log(f"[飞控] {msg.text}")


async def main(args) -> int:
    drone = System()
    log(f"连接 {args.port} …")
    await drone.connect(system_address=args.port)

    if not await wait_connected(drone):
        log("✗ 15 秒没有心跳：端口号 / 波特率 / 飞控上电，三样挨个查")
        return 1
    log("✓ 通信建立")

    st = {"armed": False, "mode": None, "alt": 0.0,
          "expect_offboard": False, "handed_over": False}

    tasks = [
        asyncio.create_task(watch_mode(drone, st)),
        asyncio.create_task(watch_armed(drone, st)),
        asyncio.create_task(watch_altitude(drone, st)),
        asyncio.create_task(watch_status(drone, st)),
    ]

    target = 0.0
    thrust = args.hover_thrust

    try:
        await asyncio.sleep(1.0)

        # ① 先发流（PX4 要求切 Offboard 前已有 setpoint）
        log("① 预发 setpoint（10Hz）…")
        for _ in range(15):
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, 0.0))
            await asyncio.sleep(0.1)

        # ② 切 Offboard
        log("② 切 Offboard")
        try:
            await asyncio.wait_for(drone.offboard.start(), 5)
        except (OffboardError, asyncio.TimeoutError) as e:
            log(f"✗ 切换失败: {e}")
            log("  查：RC_MAP_OFFB_SW 设了吗？开关 B 在允许位吗？有没有位置估计？")
            return 2
        st["expect_offboard"] = True
        log("✓ OFFBOARD")

        if args.no_arm:
            log("只发流模式：现在拨遥控器开关，看『模式 →』是否有变化。Ctrl+C 结束")
            while not st["handed_over"]:
                await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, 0.0))
                await asyncio.sleep(0.1)
            log("已被遥控器接管 ✓")
            return 0

        # ③ 解锁
        log("③ 解锁")
        try:
            await asyncio.wait_for(drone.action.arm(), 8)
        except Exception as e:
            log(f"✗ 解锁失败: {e}")
            log("  看 QGC 顶部红色预检提示；安全开关按了吗？RC 在线吗？")
            return 3
        await asyncio.sleep(1.0)
        if not st["armed"]:
            log("✗ 没等到 ARMED，中止")
            return 3

        # ④ 爬升到目标高度
        target = args.alt
        log(f"④ 开始爬升，目标 {target:.1f} m（手托到差不多高度即可）")
        climb_end = time.time() + 30
        while time.time() < climb_end:
            if st["handed_over"]:
                break
            err = target - st["alt"]
            thrust = clamp(args.hover_thrust + args.kp * err, MIN_THRUST, MAX_THRUST)
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, thrust))
            log(f"   高度 {st['alt']:5.2f} m | 推力 {thrust * 100:3.0f}% | "
                f"模式 {getattr(st['mode'], 'name', '?')}")
            if st["alt"] >= target - 0.1:
                log("✓ 到达目标高度")
                break
            await asyncio.sleep(0.5)

        # ⑤ 悬停
        if not st["handed_over"]:
            log("⑤ 悬停中 —— 现在可以打杆或拨开关抢权，Ctrl+C 也能安全退出")
            hold_end = time.time() + args.hold if args.hold > 0 else float("inf")
            last = 0.0
            while time.time() < hold_end and not st["handed_over"]:
                err = target - st["alt"]
                thrust = clamp(args.hover_thrust + args.kp * err, MIN_THRUST, MAX_THRUST)
                await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, thrust))
                if time.time() - last > 1.0:
                    last = time.time()
                    log(f"   高度 {st['alt']:5.2f} m | 推力 {thrust * 100:3.0f}%")
                await asyncio.sleep(0.1)

        if st["handed_over"]:
            log("✓ 遥控器已接管，代码停止发送，不再干预")
            return 0

        # ⑥ 缓降
        log("⑥ 缓降，交给飞控降落")
        target = 0.0
        down_end = time.time() + 12
        while time.time() < down_end and st["alt"] > 0.15:
            if st["handed_over"]:
                break
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, MIN_THRUST))
            await asyncio.sleep(0.1)
        return 0

    except KeyboardInterrupt:
        log("Ctrl+C")
        return 0

    finally:
        st["expect_offboard"] = False
        for t in tasks:
            t.cancel()

        try:
            await asyncio.wait_for(drone.offboard.stop(), 3)
        except Exception:
            pass

        # 只在"还归我们管、且还解锁着"的时候主动降落；被接管就不插手
        if st.get("armed") and not st.get("handed_over"):
            log("收尾：降落 + 上锁")
            try:
                await asyncio.wait_for(drone.action.land(), 10)
            except Exception as e:
                log(f"降落未确认: {e}")
            try:
                await asyncio.wait_for(drone.action.disarm(), 5)
            except Exception:
                pass
        log("结束")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="解锁 → 1 米悬停（Ctrl+C / 遥控器可随时接管）")
    ap.add_argument("--port", default=PORT, help=f"连接地址（默认 {PORT}）")
    ap.add_argument("--alt", type=float, default=TARGET_ALT, help="目标高度 m")
    ap.add_argument("--hold", type=float, default=HOLD_SEC, help="悬停秒数，0 = 一直悬停")
    ap.add_argument("--hover-thrust", type=float, default=HOVER_THRUST, help="悬停基准推力")
    ap.add_argument("--kp", type=float, default=KP_ALT, help="高度环增益")
    ap.add_argument("--no-arm", action="store_true", help="只发流不解锁")
    args = ap.parse_args()

    try:
        sys.exit(asyncio.run(main(args)))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
