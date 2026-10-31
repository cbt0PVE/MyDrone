#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目标追踪入口（YOLO + 单目测距 + Offboard 速度控制）。

用法:

    ① 纯视觉验证（不连飞控，先确认模型能认出人、距离大致靠谱）
        python run_tracking.py --camera 0 --no-arm

    ② 手持验证（不装桨，人拿着飞机对着自己 / 对着镜头晃动）
        python run_tracking.py --bench

    ③ 实飞追踪（飞手先起飞到 1m 以上，再运行）
        python run_tracking.py

注意：单目测距依赖"人高 = 1.7m"这个先验，误差随距离线性放大，
只适合保持距离跟随，不适合精确降落。
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

from vnav import link, safety
from vnav.config import Config, apply_sitl_preset, load_camera_matrix, parse_camera_source
from vnav.control import OffboardController
from vnav.detectors import build_detector
from vnav.tracking import TrackingMission
from vnav.vision import VisionWorker

T0 = time.time()


def log(msg=""):
    print(f"[{time.time() - T0:6.2f}s] {msg}", flush=True)


def parse_args():
    ap = argparse.ArgumentParser(description="YOLO 目标追踪")
    ap.add_argument("--port", default=None, help="串口，默认用 config.py 里的")
    ap.add_argument("--camera", default=None, help='摄像头 0/1 或 "http://ip:8080/video"')
    ap.add_argument("--weights", default=None, help="YOLO 权重路径（.pt 或 .onnx）")
    ap.add_argument("--distance", type=float, default=None, help="希望保持的距离 m")
    ap.add_argument("--alt", type=float, default=None, help="飞行高度 m")
    ap.add_argument("--bench", action="store_true", help="手持/台架：不改变高度")
    ap.add_argument("--no-arm", action="store_true", help="只跑视觉，不连飞控")
    ap.add_argument("--no-window", action="store_true", help="不弹识别窗口")
    ap.add_argument(
        "--sitl",
        action="store_true",
        help="SITL 仿真：Gazebo 相机 + udp://:14540 + 脚本自动起飞（配合 sim/run.sh）",
    )
    ap.add_argument(
        "--auto-takeoff",
        action="store_true",
        help="脚本自己解锁并爬到 --alt（SITL 默认开；实机默认关，仍由飞手起飞）",
    )
    ap.add_argument("--duration", type=float, default=0.0, help="跑多少秒后自动降落，0=一直跑")
    return ap.parse_args()


async def visual_only(cfg):
    """不连飞控，只跑检测，用来看模型和测距是否正常。"""
    K, dist, note = load_camera_matrix(cfg)
    log(f"相机内参：{note}")
    detector = build_detector(cfg, K, dist)
    worker = VisionWorker(cfg, detector)
    worker.start()
    log("[OK] 相机已启动。Ctrl+C 结束")
    try:
        while True:
            det, age = worker.latest()
            if det is None:
                log("无目标")
            else:
                log(f"id={det.marker_id} 前 {det.forward_m:5.2f} m | "
                    f"右 {det.right_m:+5.2f} m | 下 {det.down_m:+5.2f} m | 陈旧 {age:.2f}s")
            await asyncio.sleep(0.5)
    finally:
        worker.stop()


async def run(args):
    cfg = Config()
    # 先套 SITL 预设，再让命令行覆盖——这样 --port/--camera 在仿真里也能临时改
    if args.sitl:
        apply_sitl_preset(cfg)
    if args.port:
        cfg.port = args.port
    if args.camera:
        cfg.camera_source = parse_camera_source(args.camera)
    if args.weights:
        cfg.yolo_weights = args.weights
    if args.distance:
        cfg.track_distance_m = args.distance
    if args.alt:
        cfg.hover_alt_m = args.alt
    cfg.show_window = not args.no_window

    auto_takeoff = args.sitl or args.auto_takeoff

    log("======== 配置 ========")
    log(f"  端口       {cfg.port}")
    log(f"  摄像头     {cfg.camera_source}")
    log(f"  检测器     {cfg.detector} | 权重 {cfg.yolo_weights}")
    log(f"  相机安装   {cfg.camera_mount} | 人高先验 {cfg.person_height_m:.2f} m")
    log(f"  追踪距离   {cfg.track_distance_m:.2f} m")
    log(f"  高度       {cfg.hover_alt_m:.2f} m")
    if auto_takeoff:
        log("  起飞       脚本自动解锁爬升（SITL 模式）")
    log(f"  模式       {'只跑视觉' if args.no_arm else ('手持验证' if args.bench else '实飞追踪')}")
    log("======================")

    if args.no_arm:
        await visual_only(cfg)
        return 0

    K, dist, note = load_camera_matrix(cfg)
    log(f"相机内参：{note}")
    detector = build_detector(cfg, K, dist)
    worker = VisionWorker(cfg, detector)
    worker.start()
    log("[OK] 相机已启动")

    drone = None
    state = None
    controller = None
    try:
        drone = await link.connect(cfg.port, cfg.connect_timeout_s, log=log)
        state = link.TelemetryState(
            rangefinder_timeout_s=cfg.rangefinder_timeout_s,
            rangefinder_min_valid_m=cfg.rangefinder_min_valid_m,
        )
        state.start(drone)
        await asyncio.sleep(2.0)

        health = await link.read_health(drone)
        log(f"当前状态：模式 {link.describe_mode(state)} | 解锁 {state.armed} | "
            f"高度 {state.height_m:.2f}m（{state.height_source}）")

        problems = safety.check_ready(
            cfg, state, health, bench=args.bench, allow_disarmed=auto_takeoff
        )
        if problems:
            log("[X] 自检未通过：")
            for p in problems:
                log(f"    - {p}")
            return 2

        controller = OffboardController(drone, cfg, log=log)

        if auto_takeoff:
            # SITL 里没人替我们起飞，所以脚本自己来：
            #   解锁 -> 预热 setpoint 并切 OFFBOARD -> 用速度指令爬到目标高度
            log("自动起飞：解锁 ...")
            try:
                await asyncio.wait_for(drone.action.arm(), 10)
            except Exception as e:
                log(f"[X] 解锁失败：{e}")
                return 3
            for _ in range(20):
                if state.armed:
                    break
                await asyncio.sleep(0.25)
            if not state.armed:
                log("[X] 发了 arm 但没等到 ARMED，中止（不要硬来）")
                return 3
            log("[OK] 已解锁")

            await controller.start()
            log(f"爬升到 {cfg.hover_alt_m:.2f} m ...")
            reached = await controller.climb_to(cfg.hover_alt_m, state, timeout_s=30.0)
            log(
                f"{'[OK] 到达目标高度' if reached else '[!] 爬升未收敛，继续但留意高度'}"
                f" | 当前 {state.height_m:.2f} m（{state.height_source}）"
            )
        else:
            await controller.start()
            await asyncio.sleep(0.5)
            if not state.offboard:
                log("[X] 切模式后仍不在 OFFBOARD，检查 RC_MAP_OFFB_SW / 开关位置")
                return 3

        monitor = safety.SafetyMonitor(cfg)
        mission = TrackingMission(
            state, worker, controller, cfg, monitor, bench=args.bench, log=log
        )
        log("")
        log("开始追踪。遥控器随时可接管；Ctrl+C 退出。")
        log("")
        if args.duration and args.duration > 0:
            try:
                await asyncio.wait_for(mission.run(), args.duration)
            except asyncio.TimeoutError:
                log(f"到达设定时长 {args.duration:.0f}s，准备降落")
        else:
            await mission.run()
        log(f"任务结束，最终状态：{mission.phase.value}")

        # 只有还握着控制权时才自己降落；已经交还人工/已经落了就别多事
        if controller.started:
            await controller.land()
            await asyncio.sleep(1.0)
        return 0

    except KeyboardInterrupt:
        log("Ctrl+C")
        return 0
    except Exception as e:
        log(f"[X] 异常：{e}")
        return 1
    finally:
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
