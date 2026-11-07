# -*- coding: utf-8 -*-
"""Offboard 接管时的 yaw 回归测试。

历史问题：`OffboardController.start()` 预热 setpoint 时 yaw 写死 0（正北），
切 Offboard 瞬间飞机会被拽向固定方向。这里锁死"必须使用传入的当前机头朝向"。

    python tests/test_control_yaw.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.config import Config  # noqa: E402
from vnav.control import OffboardController  # noqa: E402


class FakeOffboard:
    def __init__(self):
        self.yaws = []
        self.started = False

    async def set_velocity_ned(self, velocity):
        self.yaws.append(velocity.yaw_deg)

    async def start(self):
        self.started = True


class FakeDrone:
    def __init__(self):
        self.offboard = FakeOffboard()


def test_start_uses_current_yaw():
    cfg = Config()
    cfg.control_hz = 20.0
    drone = FakeDrone()
    controller = OffboardController(drone, cfg, log=lambda *a, **k: None)

    asyncio.run(controller.start(87.3))

    assert drone.offboard.started
    assert drone.offboard.yaws, "没有发出 setpoint"
    assert all(abs(y - 87.3) < 1e-6 for y in drone.offboard.yaws), drone.offboard.yaws


def test_start_defaults_to_zero_for_old_callers():
    """老调用方不传 yaw 时仍然能跑（0 是正北，但至少不报错）。"""
    cfg = Config()
    cfg.control_hz = 5.0
    drone = FakeDrone()
    controller = OffboardController(drone, cfg, log=lambda *a, **k: None)

    asyncio.run(controller.start())

    assert drone.offboard.started
    assert all(abs(y) < 1e-9 for y in drone.offboard.yaws)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[X ] {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
