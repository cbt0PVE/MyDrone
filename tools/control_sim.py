# -*- coding: utf-8 -*-
"""控制仿真：不接飞控/相机，验证 TrackingMission 的 PID 与安全逻辑。

    python tools/control_sim.py --ki 0.0  --out logs/sim_p.csv
    python tools/control_sim.py --ki 0.15 --out logs/sim_pi.csv

模型：二维运动学，目标匀速前进，无人机按 TrackingMission 下发的机体前/右速度积分。
用途：回答“P 控制追匀速目标会不会有稳态误差”“PI 会不会振荡”。
"""

import argparse
import asyncio
import csv
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnav.config import Config  # noqa: E402
from vnav.safety import SafetyMonitor  # noqa: E402
from vnav.tracking import TrackingMission  # noqa: E402
from vnav.vision import Detection  # noqa: E402


class Sim:
    def __init__(self, distance=5.0, target_speed=0.5, target_side_speed=0.0, dt=0.05):
        self.dt = dt
        self.drone_x = 0.0
        self.drone_y = 0.0
        self.target_x = float(distance)
        self.target_y = 0.0
        self.target_vx = float(target_speed)
        self.target_vy = float(target_side_speed)
        self.t = 0.0
        self.rows = []

    def step(self, v_forward, v_right):
        self.drone_x += v_forward * self.dt
        self.drone_y += v_right * self.dt
        self.target_x += self.target_vx * self.dt
        self.target_y += self.target_vy * self.dt
        self.t += self.dt
        fwd = self.target_x - self.drone_x
        right = self.target_y - self.drone_y
        self.rows.append((self.t, self.drone_x, self.drone_y, self.target_x, self.target_y, fwd, right, v_forward, v_right))


class MockState:
    armed = True
    offboard = True
    height_m = 1.0
    height_source = "sim"
    yaw_deg = 0.0
    battery_pct = 1.0
    telemetry_age = 0.0


class MockVision:
    def __init__(self, sim):
        self.sim = sim

    def latest(self):
        fwd = self.sim.target_x - self.sim.drone_x
        right = self.sim.target_y - self.sim.drone_y
        det = Detection(
            marker_id=1,
            center_px=(320.0 + right * 10.0, 240.0),
            forward_m=fwd,
            right_m=right,
            down_m=0.3,
            yaw_deg=0.0,
            tvec=np.array([right, 0.3, fwd], dtype=float),
            confidence=0.9,
            bbox=(300.0, 100.0, 340.0, 300.0),
        )
        return det, 0.0


class MockController:
    started = True
    last_cmd = (0.0, 0.0, 0.0)

    def __init__(self, sim, dt):
        self.sim = sim
        self.dt = dt

    async def send(self, v_forward, v_right, v_down, yaw_deg):
        self.last_cmd = (v_forward, v_right, v_down)
        self.sim.step(v_forward, v_right)

    async def hold(self, yaw_deg):
        await self.send(0.0, 0.0, 0.0, yaw_deg)

    async def release(self):
        pass

    async def land(self):
        pass


def summarize(rows, target_distance, last_s=3.0):
    if not rows:
        return {}
    t_end = rows[-1][0]
    tail = [r for r in rows if r[0] >= t_end - last_s]
    fwd = [abs(r[5] - target_distance) for r in tail]
    lat = [abs(r[6]) for r in tail]
    return {
        "steady_mean_err_m": sum(fwd) / len(fwd),
        "steady_max_err_m": max(fwd),
        "lateral_mean_m": sum(lat) / len(lat),
        "final_distance_m": rows[-1][5],
    }


async def run(args):
    cfg = Config()
    cfg.control_hz = 20.0
    cfg.track_distance_m = args.distance
    cfg.kp_distance = args.kp
    cfg.ki_distance = args.ki
    cfg.distance_integral_limit = args.integral_limit
    cfg.kp_center = args.kp_center
    cfg.near_slowdown_m = args.near_slowdown

    dt = 1.0 / cfg.control_hz
    sim = Sim(args.distance, args.target_speed, args.target_side_speed, dt=dt)
    state = MockState()
    vision = MockVision(sim)
    controller = MockController(sim, dt)
    safety = SafetyMonitor(cfg)

    mission = TrackingMission(
        state, vision, controller, cfg, safety,
        bench=False,
        log=lambda msg: None,
    )
    try:
        await asyncio.wait_for(mission.run(), args.duration)
    except asyncio.TimeoutError:
        pass

    s = summarize(sim.rows, args.distance)
    print("ki=%.3f target_speed=%.2f duration=%.1fs" % (args.ki, args.target_speed, args.duration))
    for k, v in s.items():
        print("  %-20s %.3f" % (k, v))

    out = args.out
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t", "drone_x", "drone_y", "target_x", "target_y", "fwd", "right", "v_fwd_cmd", "v_right_cmd"])
            w.writerows(sim.rows)
        print("csv:", out)


def main():
    ap = argparse.ArgumentParser(description="TrackingMission 二维控制仿真")
    ap.add_argument("--ki", type=float, default=0.3, help="距离积分增益；0=P-only")
    ap.add_argument("--kp", type=float, default=0.8)
    ap.add_argument("--kp-center", type=float, default=1.2)
    ap.add_argument("--near-slowdown", type=float, default=0.0,
                    help="误差小于此值降速一半；0=关闭，用于验证 PI 收敛")
    ap.add_argument("--integral-limit", type=float, default=2.0)
    ap.add_argument("--distance", type=float, default=2.5, help="目标保持距离")
    ap.add_argument("--target-speed", type=float, default=0.5, help="目标前向速度 m/s")
    ap.add_argument("--target-side-speed", type=float, default=0.0, help="目标横向速度 m/s")
    ap.add_argument("--duration", type=float, default=12.0)
    ap.add_argument("--out", default="logs/control_sim.csv")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
