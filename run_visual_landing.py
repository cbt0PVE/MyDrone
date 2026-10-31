#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉追踪降落 —— 阶段四：实机自主降落 / 手持闭环验证。

两种用法：

    ① 手持验证（不装桨！）—— 验证视觉方向的正负号是否写对
        python run_visual_landing.py --bench

       人托着飞机在 ArUco 标签上方晃动：
       - 往左偏，看指令里的"右"是不是正值（飞机应该往右修正）
       - 往前往后同理
       只看指令符号，不必真飞。

    ② 实飞降落 —— 由飞手手动起飞到 1 米以上，再运行本脚本
        python run_visual_landing.py

       脚本会自己切 Offboard、对准标签、缓慢下降，到 0.35 米交给 PX4 落地。

任何时刻：遥控器打杆/拨开关会立即交还控制权；Ctrl+C 也会安全退出。
"""

import argparse
import asyncio
import sys
import time

# Windows 控制台是 GBK，遇到无法编码的字符会崩，先放宽
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from vnav import link, safety
from vnav.config import Config, load_camera_matrix, parse_camera_source
from vnav.control import OffboardController
from vnav.mission import VisualLandingMission
from vnav.vision import ArucoTracker, VisionWorker

T0 = time.time()


def log(msg=""):
    print(f"[{time.time() - T0:6.2f}s] {msg}", flush=True)


def parse_args():
    ap = argparse.ArgumentParser(description="视觉追踪降落 / 手持闭环验证")
    ap.add_argument("--port", default=None, help="串口，默认用 config.py 里的")
    ap.add_argument("--camera", default=None, help='摄像头：0/1 或 "http://ip:8080/video"')
    ap.add_argument("--alt", type=float, default=None, help="追踪高度 m")
    ap.add_argument("--marker-size", type=float, default=None, help="标签边长 m")
    ap.add_argument("--bench", action="store_true", help="手持/台架验证：只对准不下降")
    ap.add_argument("--no-window", action="store_true", help="不弹识别窗口")
    return ap.parse_args()


async def run(args):
    # ---------- 1. 组装配置 ----------
    cfg = Config()
    if args.port:
        cfg.port = args.port
    if args.alt:
        cfg.hover_alt_m = args.alt
    if args.marker_size:
        cfg.marker_size_m = args.marker_size
    cfg.camera_source = parse_camera_source(args.camera) if args.camera else cfg.camera_source
    cfg.show_window = not args.no_window

    log("======== 配置 ========")
    log(f"  端口        {cfg.port}")
    log(f"  模式        {'手持验证（不下降）' if args.bench else '实飞追踪降落'}")
    log(f"  追踪高度    {cfg.hover_alt_m:.2f} m")
    log(f"  标签边长    {cfg.marker_size_m*100:.1f} cm")
    log(f"  控制频率    {cfg.control_hz:.0f} Hz")
    log("======================")

    # ---------- 2. 视觉初始化 ----------
    K, dist, note = load_camera_matrix(cfg)
    log(f"相机内参：{note}")
    tracker = ArucoTracker(cfg, K, dist)
    worker = VisionWorker(cfg, tracker)
    worker.start()
    log("[OK] 相机已启动")

    drone = None
    state = None
    controller = None
    try:
        # ---------- 3. 连接飞控 ----------
        log("连接飞控 ...")
        drone = await link.connect(cfg.port, cfg.connect_timeout_s, log=log)

        state = link.TelemetryState(rangefinder_timeout_s=cfg.rangefinder_timeout_s)
        state.start(drone)
        await asyncio.sleep(2.0)  # 等遥测回填

        health = await link.read_health(drone)
        log(f"当前状态：模式 {link.describe_mode(state)} | 解锁 {state.armed} | "
            f"高度 {state.height_m:.2f}m（{state.height_source}） | "
            f"RC {'在线' if state.rc_available else '未知'}")

        # ---------- 4. 航前自检 ----------
        problems = safety.check_ready(state, health, bench=args.bench)
        if problems:
            log("[X] 自检未通过：")
            for p in problems:
                log(f"    - {p}")
            return 2

        # ---------- 5. 进入 Offboard ----------
        controller = OffboardController(drone, cfg, log=log)
        await controller.start()
        await asyncio.sleep(0.5)

        if not state.offboard:
            log("[X] 切模式后仍不在 OFFBOARD，检查 RC_MAP_OFFB_SW / 开关位置")
            return 3

        # ---------- 6. 跑任务 ----------
        monitor = safety.SafetyMonitor(cfg)
        mission = VisualLandingMission(
            state, worker, controller, cfg, monitor, bench=args.bench, log=log
        )
        log("")
        log("开始任务。遥控器随时可接管；Ctrl+C 退出。")
        log("")
        await mission.run()
        log(f"任务结束，最终状态：{mission.phase.value}")
        return 0

    except KeyboardInterrupt:
        log("Ctrl+C")
        return 0
    except Exception as e:
        log(f"[X] 异常：{e}")
        return 1
    finally:
        # 顺序很重要：先停视觉，再交还控制，最后停遥测
        try:
            worker.stop()
        except Exception:
            pass
        if controller is not None:
            try:
                await controller.release()
            except Exception:
                pass
        if state is not None:
            try:
                await state.stop()
            except Exception:
                pass
        log("结束")


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run(parse_args())))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
