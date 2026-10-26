# SITL 仿真环境（WSL）

> 环境不在 Windows 原生，而在 **WSL Ubuntu 24.04** 里。这是对的——PX4 官方的
> Windows 方案也是 WSL2。

## 零、实测结论（2026-10-27，已验证）

```
px4_sitl 启动： INFO [px4] Startup script returned successfully
MAVSDK 连接：  [OK] 已连接（1.1 秒收到心跳）
```

也就是说**第 2 周的 SITL 欠账已经清了**，不用再装任何东西。

## 一、已有什么

| 组件 | 版本/位置 | 状态 |
| --- | --- | --- |
| WSL 发行版 | Ubuntu 24.04 (noble)，WSL2 | ✅ |
| Gazebo | **gz Harmonic**（gz-sim 8） | ✅ 已装 |
| ROS 2 | Jazzy（`/opt/ros/jazzy`） | ✅ 已装 |
| PX4-Autopilot | `/home/helta/src/PX4-Autopilot`，commit `5eecffe` | ✅ 已装 |
| PX4 SITL 二进制 | `build/px4_sitl_default/bin/px4`（56MB） | ✅ **已编译** |
| MAVSDK | Python 3.12 用户目录，**3.15.3** | ✅ 可用 |
| OpenCV | 4.6.0（比 Windows 上的 4.13 老） | ⚠️ 见下方注意 |

## 二、启动仿真

```powershell
# 无界面（省资源，先验证能起来）
wsl -d Ubuntu -- bash -lc "cd /home/helta/src/PX4-Autopilot && HEADLESS=1 make px4_sitl gz_x500"

# 带 Gazebo 界面（需要 WSLg，Win11 默认有）
wsl -d Ubuntu -- bash -lc "cd /home/helta/src/PX4-Autopilot && make px4_sitl gz_x500"
```

看到 `INFO [commander] Ready for takeoff!` 就算起来了。

> **必须在你自己的 WSL 终端里跑**（开始菜单搜 Ubuntu 打开窗口）。
> 如果让脚本/AI 代跑，父进程退出时 make 会被一起杀掉，
> 日志里会看到 `ninja: build stopped: interrupted by user`。

换机型：`gz_x500` / `gz_x500_depth`（带深度相机）/ `gz_x500_mono_cam`（带单目相机）。

## 三、在 WSL 里跑我们的脚本

PX4 SITL 默认把 MAVLink 发到 `127.0.0.1:14540`，所以**脚本要在 WSL 里跑**，
不要在 Windows 侧连（跨 WSL2 的 UDP 回环不通，除非改 PX4 的目标地址）。

```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/c/Users/10545/Desktop/drone && python3 hover_test.py --port udp://:14540"
```

第一次跑之前确认依赖（WSL 里已有 mavsdk 3.15.3）：

```bash
wsl -d Ubuntu -- python3 -c "from mavsdk import System; print('ok')"
```

## 四、注意

1. **WSL 里的 OpenCV 是 4.6**，没有 `cv2.aruco.ArucoDetector`（4.7 才有）。
   `vnav` 已经做了兼容：没有新 API 时自动退回 `detectMarkers`。但
   `tools/make_aruco.py` 用了 `generateImageMarker`（4.6 没有），所以生成标签请在 Windows 上做。
2. **相机仿真**：`gz_x500_mono_cam` 带相机，画面可以通过 Gazebo Transport 或
   ROS 2 `ros_gz_bridge` 取出来。这是后面做"仿真视觉闭环"的入口——
   没有实体相机时，这条路能让视觉算法跑真数据。
3. **GUI 起不来**多半是 WSLg 问题：先试 `HEADLESS=1`，确认仿真本身没问题再调显示。

## 五、这对课程意味着什么

课程第 2 周要求"装 PX4 SITL 与 Gazebo，跑通起飞悬停，接 MAVROS"：

- SITL + Gazebo：✅ 已具备
- 起飞悬停：用 `hover_test.py --port udp://:14540` 即可验证（不需要真机）
- MAVROS：ROS 2 Jazzy 已装，`ros-humble-mavros` 是 ROS1 的说法，Jazzy 对应 `mavros` 包，
  需要单独 `apt install ros-jazzy-mavros`。**这条是欠账，但不是必须**——MAVSDK 已经能完成同样的事。
