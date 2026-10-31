#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""联通 -> 解锁 -> 1 米悬停。Ctrl+C 或遥控器接管都会安全让出。

端口在下面 PORT 那一行改，不用管别的。

常用:
    python hover_test.py --no-arm        # 只发流，不解锁（先验证模式切换）
    python hover_test.py                 # 手托 1 米悬停

手托步骤:
    1. --no-arm 跑一遍：能进 OFFBOARD、拨开关能切出，说明链路通
    2. 装桨、站侧面、双手托住机架（全程别松手）
    3. 正常运行：解锁后推力升到悬停点，你把飞机托到 1 米左右
    4. Ctrl+C 或拨遥控器开关，脚本自动让出

安全:
    - 推力限制在 MIN_THRUST ~ MAX_THRUST
    - 遥控器一接管就停发 setpoint，绝不和飞手抢
    - 永不调用 kill()
"""

import argparse
import asyncio
import sys
import signal
import time

# Windows 控制台默认 GBK，遇到无法编码的字符会直接崩溃。先放宽错误处理。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from mavsdk import System
from mavsdk.offboard import Attitude, OffboardError
from mavsdk.telemetry import FlightMode

# ================= 端口：改这一行 =================
# 数传电台（SiK/3DR 之类）通常是 57600，写成 "serial://COM5:57600"
# 飞控 USB 直连通常是 115200，写成 "serial://COM5:115200"
# 端口号在设备管理器 -> 端口(COM 和 LPT) 里看；插拔不同 USB 口会变
PORT = "serial://COM6:115200"
# =================================================

# ============ 飞行参数 ============
# 这台机马力很足：实测 16% 推力就能爬到 4~5 米，所以推力范围整体压得很低。
TARGET_ALT = 1.0        # 目标高度 m
HOLD_SEC = 0.0          # 0 = 一直悬停到 Ctrl+C
HOVER_THRUST = 0.16     # 悬停基准推力；若解锁后一直往上爬，说明悬停点更低，下调试 0.14/0.15
KP_ALT = 0.05           # 高度环增益；推重比越高增益要越小，0.05 已经够猛
MIN_THRUST = 0.04
MAX_THRUST = 0.25       # 安全上限，只比悬停高 50%，防止一冲就上天

# 控高时优先用 TFmini 激光（离地高度）；命令行 --no-laser 可强制回退气压计
LASER_ENABLE = True

# ---- Ctrl+C 处理 ----
# 不能让它抛 KeyboardInterrupt：那样 asyncio.run 会立刻销毁 gRPC 通道，
# finally 里的 land() 根本发不出去（实测报 Connection refused）。
# 改成"置标志位 -> 主循环正常退出 -> 通道还在 -> 降落能发"。
STOP = False


def _on_sigint(signum, frame):
    global STOP
    if STOP:  # 第二次 Ctrl+C 才强制中断
        raise KeyboardInterrupt
    STOP = True
    print("\n[!] 收到 Ctrl+C：正在走安全降落流程；再按一次 Ctrl+C 会强制退出", flush=True)

T0 = time.time()


# ---------------------------------------------------------------- 输出


def log(msg=""):
    print(f"[{time.time() - T0:6.2f}s] {msg}", flush=True)


def stage(no, total, title, detail=""):
    log("")
    log(f"---- [{no}/{total}] {title} ----")
    if detail:
        log(f"       {detail}")


def hint(lines):
    for line in lines:
        log(f"       > {line}")


async def wait_connected(drone, timeout=15.0) -> bool:
    async def _wait():
        async for state in drone.core.connection_state():
            if state.is_connected:
                return True

    try:
        return await asyncio.wait_for(_wait(), timeout)
    except asyncio.TimeoutError:
        return False


# ---------------------------------------------------------------- 遥测


async def watch_mode(drone, st):
    async for mode in drone.telemetry.flight_mode():
        if mode != st.get("mode"):
            st["mode"] = mode
            log(f"模式变更 -> {getattr(mode, 'name', mode)}")
            if st.get("expect_offboard") and mode != FlightMode.OFFBOARD:
                st["handed_over"] = True
                log("       (已离开 OFFBOARD，判定为人工接管)")


async def watch_armed(drone, st):
    async for armed in drone.telemetry.armed():
        if armed != st.get("armed"):
            st["armed"] = armed
            log("ARMED 已解锁" if armed else "DISARMED 已上锁")


async def watch_altitude(drone, st):
    async for pos in drone.telemetry.position():
        st["baro"] = pos.relative_altitude_m  # 气压计 / EKF 高度


async def compute_height(st):
    """后台统一决定"当前高度"用哪个源，写回 st["alt"]。

    控制循环只读 st["alt"]，不用关心来源；激光有效就用激光（离地高度），
    否则回退气压计。日志里再标出来源，方便判断是不是在依赖激光。
    """
    while True:
        if use_laser(st):
            st["alt"] = st["dist"]
            st["src"] = "laser"
        else:
            st["alt"] = st.get("baro", 0.0)
            st["src"] = "baro"
        await asyncio.sleep(0.05)


async def watch_distance(drone, st):
    """TFmini 激光：PX4 以 DISTANCE_SENSOR 发出原始测距值。"""
    async for d in drone.telemetry.distance_sensor():
        st["dist"] = d.current_distance_m
        st["dmin"] = d.minimum_distance_m or 0.0
        st["dmax"] = d.maximum_distance_m or 0.0
        st["dist_t"] = time.monotonic()


def use_laser(st) -> bool:
    """激光值是否可以拿来控高。

    四条都满足才算数：有值、1 秒内更新过、在量程内、且高于 0.15m。
    最后一条是为了排掉"贴地时钳在量程下限 0.10"的假数据。
    """
    if not LASER_ENABLE:
        return False
    d = st.get("dist")
    if d is None or time.monotonic() - st.get("dist_t", 0) > 1.0:
        return False
    dmin, dmax = st.get("dmin", 0.0), st.get("dmax", 0.0)
    if dmax > 0 and not (dmin <= d <= dmax):
        return False
    return d >= 0.15


def height_of(st):
    """返回 (用于控高的高度, 来源字符串)。激光优先，否则回退气压计。"""
    if use_laser(st):
        return st["dist"], "laser"
    return st.get("alt", 0.0), "baro"


async def watch_status(drone, st):
    async for msg in drone.telemetry.status_text():
        log(f"[飞控] {msg.text}")


async def watch_rc(drone, st):
    async for rc in drone.telemetry.rc_status():
        if rc.available != st.get("rc"):
            st["rc"] = rc.available
            log("RC 链路有信号" if rc.available else "! RC 链路已断开")


# ---------------------------------------------------------------- 主流程


async def main(args) -> int:
    total = 5

    # 用标志位处理 Ctrl+C，保证降落指令能真正发出去（见文件顶部说明）
    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except Exception:
        pass

    log("======== 配置 ========")
    log(f"  端口       {args.port}")
    log(f"  目标高度   {args.alt:.1f} m")
    log(f"  悬停推力   {args.hover_thrust * 100:.0f}%（范围 {MIN_THRUST*100:.0f}%~{MAX_THRUST*100:.0f}%）")
    log(f"  高度增益   {args.kp}")
    log(f"  模式       {'只发流，不解锁' if args.no_arm else '解锁 + 悬停'}")
    log("======================")

    # ---- 1 链路 ----
    stage(1, total, "建立链路", f"连接 {args.port}")
    drone = System()
    try:
        await asyncio.wait_for(drone.connect(system_address=args.port), 15)
    except Exception as e:
        hint([f"打开端口失败: {e}",
              "改文件顶部的 PORT 常量，或命令行 --port 指定"])
        return 1

    if not await wait_connected(drone):
        hint(["15 秒没有心跳，按顺序查：",
              "1. 端口号对吗（设备管理器 -> 端口）",
              "2. 波特率对吗（数传 57600 / USB 115200）",
              "3. 飞控上电了吗 / 安全开关按了吗",
              "4. QGC 是不是正占着这个串口"])
        return 1
    log("       [OK] 通信建立")

    st = {"armed": False, "mode": None, "alt": 0.0, "rc": None,
          "expect_offboard": False, "handed_over": False}

    tasks = [
        asyncio.create_task(watch_mode(drone, st)),
        asyncio.create_task(watch_armed(drone, st)),
        asyncio.create_task(watch_altitude(drone, st)),
        asyncio.create_task(watch_distance(drone, st)),
        asyncio.create_task(compute_height(st)),
        asyncio.create_task(watch_status(drone, st)),
        asyncio.create_task(watch_rc(drone, st)),
    ]

    try:
        await asyncio.sleep(1.0)

        # ---- 2 健康检查 ----
        stage(2, total, "航前状态")
        log(f"       当前模式 {getattr(st['mode'], 'name', '未知')} | "
            f"解锁 {st['armed']} | RC {'在线' if st['rc'] else '不在线或未知'}")
        try:
            h = await asyncio.wait_for(anext(drone.telemetry.health()), 3)
            log(f"       本地位置 {h.is_local_position_ok} | "
                f"全局位置 {h.is_global_position_ok} | 家位置 {h.is_home_position_ok}")
            if not h.is_local_position_ok:
                hint(["没有本地位置估计。PX4 可能因此拒绝 Offboard ——",
                      "室内无 GPS 时这是最常见的一道坎，先往下跑看第 3 步结果"])
        except Exception:
            log("       （健康状态读取超时，跳过）")

        # ---- 3 预发 setpoint + 切 Offboard ----
        stage(3, total, "预发 setpoint 并切 OFFBOARD",
              "PX4 要求切模式前已有数据流，所以先发 1.5 秒")
        for i in range(15):
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, 0.0))
            await asyncio.sleep(0.1)
            if i in (4, 9, 14):
                log(f"       已发送 {i + 1}/15")

        try:
            await asyncio.wait_for(drone.offboard.start(), 5)
        except (OffboardError, asyncio.TimeoutError) as e:
            hint([f"切换失败: {e}", "按顺序查：",
                  "1. 参数 RC_MAP_OFFB_SW 设了吗？开关 B 在允许位吗？",
                  "2. 第 2 步若显示没有本地位置估计，大概率卡在这里",
                  "3. 改完参数重启飞控了吗？"])
            return 2
        st["expect_offboard"] = True
        log("       [OK] 已进入 OFFBOARD，setpoint 正在被接受")

        if args.no_arm:
            log("")
            log("======== 只发流模式 ========")
            log("电机不转。现在去拨遥控器开关 B，观察上面『模式变更』。")
            log("Ctrl+C 结束。")
            while not st["handed_over"]:
                await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, 0.0))
                await asyncio.sleep(0.1)
            log("[OK] 遥控器接管成功 —— 开关绑定是对的")
            return 0

        # ---- 4 解锁 ----
        stage(4, total, "解锁")
        try:
            await asyncio.wait_for(drone.action.arm(), 8)
        except Exception as e:
            hint([f"解锁失败: {e}", "看 QGC 顶部红色预检提示，常见：",
                  "1. 安全开关没长按到常亮",
                  "2. RC 未校准 / RC 不在线",
                  "3. 磁罗盘、加速度计没校准",
                  "4. 电池电压过低"])
            return 3
        await asyncio.sleep(1.0)
        if not st["armed"]:
            hint(["没等到 ARMED 状态。飞控可能收到指令但拒绝执行，看上面 [飞控] 提示"])
            return 3
        log("       [OK] 已解锁，动力系统带电")

        # ---- 5 爬升 + 悬停 ----
        stage(5, total, f"爬升到 {args.alt:.1f} m 并悬停",
              "手托的话现在把飞机托起来，它会自己找平衡")
        target = args.alt
        climb_end = time.time() + 30
        sat_since, alt_at_sat = None, 0.0
        while time.time() < climb_end and not st["handed_over"] and not STOP:
            err = target - st["alt"]
            thrust = max(MIN_THRUST, min(MAX_THRUST, args.hover_thrust + args.kp * err))
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, thrust))
            log(f"       高度 {st['alt']:5.2f} m({st.get('src', '?')}) | 推力 {thrust * 100:3.0f}% | "
                f"模式 {getattr(st['mode'], 'name', '?')}")

            saturated = thrust >= MAX_THRUST - 0.001
            if saturated and sat_since is None:
                sat_since, alt_at_sat = time.time(), st["alt"]
            elif saturated and time.time() - sat_since > 3 and st["alt"] - alt_at_sat < 0.1:
                hint([f"推力顶到上限 {MAX_THRUST*100:.0f}% 三秒还没离地：",
                      "可能 桨装反 / 电池电压低 / 悬停推力设太小"])
                sat_since = None
            elif not saturated:
                sat_since = None

            if st["alt"] >= target - 0.1:
                log("       [OK] 到达目标高度")
                break
            await asyncio.sleep(0.5)

        if st["handed_over"]:
            log("[OK] 遥控器已接管，代码停止发送")
            return 0

        # ---- 悬停段 ----
        log("")
        log("-------- 悬停中（Ctrl+C 退出 / 打杆或拨开关可抢权）--------")
        hold_end = time.time() + args.hold if args.hold > 0 else float("inf")
        last_print = 0.0
        while time.time() < hold_end and not st["handed_over"] and not STOP:
            err = target - st["alt"]
            thrust = max(MIN_THRUST, min(MAX_THRUST, args.hover_thrust + args.kp * err))
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, thrust))
            if time.time() - last_print > 1.0:
                last_print = time.time()
                log(f"       高度 {st['alt']:5.2f} m({st.get('src', '?')}) | 推力 {thrust * 100:3.0f}%")
            await asyncio.sleep(0.1)

        if st["handed_over"]:
            log("[OK] 遥控器已接管，代码停止发送")
            return 0

        # ---- 收尾 ----
        log("")
        if STOP:
            log("收到 Ctrl+C：跳过剩余悬停，直接缓降")
        log("-------- 缓降 --------")
        for _ in range(120):  # 最长 12 秒
            if st["handed_over"] or st["alt"] <= 0.15:
                break
            await drone.offboard.set_attitude(Attitude(0.0, 0.0, 0.0, MIN_THRUST))
            await asyncio.sleep(0.1)
        return 0

    except KeyboardInterrupt:
        log("检测到 Ctrl+C")
        return 0

    finally:
        st["expect_offboard"] = False

        # 顺序很重要：先降落并等上锁，再取消遥测任务。
        # 任务一取消，st["armed"] 就不再更新，也就没法确认到底上锁没有。
        try:
            await asyncio.wait_for(drone.offboard.stop(), 3)
        except Exception:
            pass

        if st.get("armed") and not st.get("handed_over"):
            log("收尾：降落 + 上锁")
            try:
                await asyncio.wait_for(drone.action.land(), 10)
                log("       [OK] 降落指令已送达")
            except Exception as e:
                log(f"       降落指令发送失败: {e}")

            # PX4 落地后会按 COM_DISARM_LAND 自动上锁，这里等它确认
            for _ in range(24):  # 最多 12 秒
                if not st.get("armed"):
                    break
                await asyncio.sleep(0.5)
            if st.get("armed"):
                log("       [!] 仍未上锁：可能还在下降途中，或传感器认为未落地。请用遥控器确认")
            else:
                log("       [OK] 已上锁")

        for t in tasks:
            t.cancel()
        log("结束")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="解锁 -> 1 米悬停（Ctrl+C / 遥控器可接管）"
    )
    ap.add_argument("--port", default=PORT, help=f"连接地址（默认 {PORT}）")
    ap.add_argument("--alt", type=float, default=TARGET_ALT, help="目标高度 m")
    ap.add_argument("--hold", type=float, default=HOLD_SEC, help="悬停秒数，0=一直悬停")
    ap.add_argument("--hover-thrust", type=float, default=HOVER_THRUST, help="悬停基准推力")
    ap.add_argument("--kp", type=float, default=KP_ALT, help="高度环增益")
    ap.add_argument("--no-arm", action="store_true", help="只发流不解锁")
    ap.add_argument("--no-laser", action="store_true", help="不用 TFmini，强制用气压计控高")
    args = ap.parse_args()

    # --no-laser 时强制回退气压计（模块级作用域，直接赋值即可）
    LASER_ENABLE = not args.no_laser

    try:
        sys.exit(asyncio.run(main(args)))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
