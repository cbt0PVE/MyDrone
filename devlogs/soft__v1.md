# 📝 软件开发日志 (Software Development Log)

## 📌 项目基本信息
* **项目名称：** MyDrone AI - 基于计算机视觉与异步控制的自主目标追踪系统
* **开发环境：** macOS (Apple Silicon), Python 3.14 (Homebrew), PX4 Autopilot SITL v1.14+, jMAVSim 3D Simulation
* **核心技术栈：** OpenCV (感知端), MAVSDK-Python / Asyncio (控制端), C++11/kqueue (服务器基础设施底座)

---

## 📅 2026-05-22 ~ 2026-05-23
### 🚀 版本里程碑：`v0.4.0-alpha (完全体闭环合流通关)`

### 1. 本次开发核心目标
将前期独立调试完成的 **OpenCV 色彩空间感知模块** 与 **MAVSDK 异步控制外环** 融合成统一的闭环控制主程序（`src/main_tracker.py`），实现由底层硬件级多路复用（C++ kqueue/Reactor 模型设计思想启发）到上层 AI 视觉伺服（Visual Servoing）的完整链路打通。

### 2. 攻坚克难记录 (Bug & Troubleshooting Ledger)

| 序号   | 遇到的核心死锁/报错 (Issue)                             | 根因分析 (Root Cause)                                        | 解决方案 (Resolution)                                        |
| :----- | :------------------------------------------------------ | :----------------------------------------------------------- | :----------------------------------------------------------- |
| **01** | `ModuleNotFoundError: No module named 'cv2'`            | Mac 环境下存在多套 Python 解释器（系统自带、Xcode 附带与 Homebrew 环境），新开终端标签页时快捷别名（`alias`）未自动刷新，导致解释器错配。 | 明确指定 Homebrew 纯净路径下的物理解释器进行精准轰炸：`/opt/homebrew/bin/python3 main_tracker.py`。 |
| **02** | `Preflight Fail: ekf2 missing data` / `GPS fix too low` | PX4 仿真底座刚拉起时，扩展卡尔曼滤波器（EKF2）和虚拟定位需要静态数据收敛，应用层 `health()` 检查函数死锁，不放行后续代码。 | 在控制外环测试阶段，直接注销（注释掉）`main()` 函数中的航前 GPS 强健性死循环，实现“越塔”直接解锁。 |
| **03** | `Preflight Fail: Battery unhealthy`                     | PX4 工业级飞控算法底座模拟了物理电池真实放电，后台静置过久或默认阈值过高触发低电量保护锁死电机。 | 在 PX4 原生交互命令行 `pxh>` 中强制废除电量拦截开关，轰入：`param set COM_ARM_BAT_MIN 0`。 |
| **04** | `ImportError: ... 'VelocityBodyYawSpeed'`               | MAVSDK-Python 库经历版本升级优化后，对内部类名与命名空间进行了重构，导致旧教程中的类名失效。 | 利用 Python 自省机制（`dir()`）强行刺探出当前版本的物理真名，将导入与控制格式规范对齐为最新的 **`VelocityNedYaw`** 与 **`set_velocity_ned`**。 |
| **05** | 飞机转桨但无法离地悬停 / `NameError`                    | 1. 占位包残留了未定义的旧变量名；2. 起飞指令后 `sleep(5)` 时限太短，飞机尚未爬升至预定高度稳住位置环，即被强行切入 Offboard 速度注入，导致飞控底层安全死锁。 | 1. 彻底清理 138 行残留变量；2. 将自动起飞后的挂起等待时限由 5秒 放大至 **12秒**，确保 PX4 终端吐出 `Hover detected` 后再优雅移交 AI 控制权。 |

### 3. 当前系统架构与数据闭环

```text
 ┌────────────────────────────────────────────────────────┐
 │                                                        │
 ▼                                                        │ (物理视窗反馈)
┌──────────────┐   像素误差 (ex, ey)   ┌──────────────┐   │
│  OpenCV 感知  ├─────────────────────>│  PD 控制律   ├───┘
└──────────────┘                       └──────┬───────┘
                                              │
                                         转换成速度向量
                                       (vx, vy, vz, yaw)
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ MAVSDK 飞控  │ (100Hz 异步协程注入)
                                       └──────────────┘