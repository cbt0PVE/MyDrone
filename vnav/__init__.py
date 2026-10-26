# -*- coding: utf-8 -*-
"""vnav —— 视觉导航控制包（阶段四：安全防护 + 手持闭环验证）

模块划分：

    config.py   所有可调参数集中在这里
    vision.py   ArUco 检测、PnP 位姿解算、视觉 PID
    link.py     MAVSDK 连接与遥测状态缓存
    safety.py   安全看门狗（丢目标 / 链路断 / 遥控器抢权）
    control.py  Offboard 速度指令下发与退出
    mission.py  视觉追踪降落状态机

设计原则：任何一步出错，默认动作是"停住并交还人工"，而不是继续飞。
"""

__all__ = ["config", "vision", "link", "safety", "control", "mission"]
__version__ = "0.1.0"
