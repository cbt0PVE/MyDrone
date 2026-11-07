# 当前状态

> **每次收工前更新这里。** 这是跨机器唯一的"记忆"，不写就等于丢。
> 格式：写结论，不写过程流水账。

最后更新：2026-11-07 · Windows（香橙派 5 Pro 开机 + SSH 免密打通，见 `docs/BOARD_SSH.md`）

## 阶段

按课程十周计划推进（逐周对照见 `docs/ROADMAP.md`）：

- **硬件超前**：装机完成、能飞，**RC 与 Offboard 已可切换（已验证）**。
- **仿真已补齐**：WSL 里的 PX4 SITL + Gazebo Harmonic 实测可用，MAVSDK 1.1s 连上（见 `docs/SITL_GUIDE.md`）。
- **第 3 周已完成**：YOLOv8n 训练 mAP@0.5 = 0.7526。
- **第 2 项下一步（SITL 相机闭环）已完成**：Gazebo 相机 → YOLO → 测距 → 速度闭环，
  收敛到 2.5m 并稳定，见 `docs/SITL_CAMERA.md`。
- **缺口**：机载电脑（香橙派 5 Pro）**已开机并验证**（Ubuntu 22.04 / NPU v0.9.6 / 16GB，SSH 免密可用）；相机仍未采购；**相机未标定**（`calib.json` 不存在）。

## 已完成

- 通读早期三个脚本，结论见 `docs/CODE_NOTES.md`。
- 2026-10-27 实测 WSL 仿真链路：PX4 SITL（`gz_x500`）启动成功，MAVSDK `udp://:14540` 1.1 秒连上，见 `docs/SITL_GUIDE.md`。
- 2026-10-27 **第 3 周训练完成**：YOLOv8n 单类 person，mAP@0.5 = **0.7526**，mAP@0.5:0.95 = 0.4983；4060 上 66.3 FPS（PyTorch）/ 45.7 FPS（ONNX-CPU）。产物与图表见 `docs/WEEK3_RESULTS.md`。
- 2026-11-07 **香橙派 5 Pro 首次开机成功**：Ubuntu 22.04 / 内核 5.10.160 / RKNPU v0.9.6 / 16GB；
  空载 42–43°C；已配 Windows 免密 SSH（`ssh orangepi`），可脱离显示器，见 `docs/BOARD_SSH.md`。
- 2026-11-07 **飞行日志 + 飞行模式脚本**：`vnav/flightlog.py`（文本
  `[级别][时间](字段=值)` + JSONL 双写，2Hz 状态、事件立即写）；`run_tracking.py` 已接入
  （配置快照、自检、解锁、Offboard、任务阶段、异常、退出）；`tools/flight_mode.sh`
  可一键关/开 WiFi+蓝牙，板子实测 `status` 正常。见 `docs/LOGGING.md`。
- 2026-11-07 **RKNN 代码路径 + 板上实测**：`RknnDetector` 支持 **3 头输出**
  （DFL softmax + sigmoid + 复用 NMS/测距）；3 头 INT8 模型在板上检出人，
  **conf 0.831，与 ONNX 框 IoU 0.9916，推理 18.3 FPS，端到端 13.7 FPS**。
  全模型 INT8 的分类通道会归零，已放弃；FP16 4.8 FPS、ONNX CPU 6.9 FPS 仅作对照。
  见 `docs/RKNN.md`。
- 2026-11-07 **板上 MAVSDK 预检 + 批量精度**：
  - `mavsdk 3.15.3` aarch64 轮子可用，`mavsdk_server` 可执行，`vnav.link` import 正常；
  - 40 张 COCO person 图 ONNX↔RKNN **最佳匹配 IoU 0.9899**（min 0.9757），
    top-1 0.9128（多人图选人不同），分数差均值 0.0123，**40/40 都检出**。
  - 工具：`tools/eval_rknn_batch.py`。
- 2026-11-07 **板上视频链路**：合成 120 帧行人视频，`open_camera → RknnDetector
  → 标注/写视频` 跑通，**11.2 FPS**（含读帧/标注/写盘），93/120 帧检出
  （后半段人走出画面）。工具 `tools/video_pipeline.py`。
- 2026-11-07 **目标时序滤波**：新增 `vnav/tracker.py`（EMA + 跳变抑制），接进
  `TrackingMission`；控制用平滑值，安全看门狗仍用原始检测，丢目标不会被滤波掩盖。
  参数：`target_filter_alpha=0.35`、`max_jump=1.5m`、`max_miss=5`；测试 4/4。
- 2026-10-31 **SITL 相机视觉闭环打通**（不依赖实体相机）：
  - `vnav/camera.py`：取图源抽象（本地摄像头 / 网络流 / **Gazebo Transport**），
    `VisionWorker` 硬编码的 `cv2.VideoCapture` 已收口
  - `vnav/detectors.py`：新增 `OnnxDetector`（onnxruntime，**不需要 torch**）
  - `sim/`：`setup.sh`（拉 Fuel 行人模型 + 建链）、`run.sh`（起 SITL → 跑闭环 → 收尾）、
    `worlds/mydrone_track.sdf`（默认世界 + 行人 actor）
  - `run_tracking.py`：新增 `--sitl` / `--auto-takeoff` / `--duration`
  - **实测**：解锁 → OFFBOARD → 爬升 → 从 5.85m 逼近并稳定在 **2.47–2.50m**（目标 2.50）
    → 到点降落 → 退出 Offboard。详见 `docs/SITL_CAMERA.md`
  - 修了两个历史 bug：`tracking.py` 高度符号写反（低于目标反而下降）；
    `run_tracking.py` 没 `import asyncio` + 把 `SafetyMonitor.check_ready` 当模块函数调
    （**入口脚本此前从未被真正执行过**）
  - Gazebo 真值对照发现：baro 高度偏高约 +0.12m 且滞后；单目测距近距离偏低约 7%
- 2026-10-31 **YOLO 接入 vnav**：`vnav/detectors.py`（单目测距 + ByteTrack ID）、`vnav/tracking.py`（追踪任务）、`run_tracking.py`（纯视觉 / 手持 / 实飞三种模式）。冒烟测试 5/5 通过；在真实 COCO 图上跑出 2.8–8.2m 的距离估计。
- 2026-10-31 **TFmini-S 已接入**，`hover_test.py` 控高改为激光优先、气压计兜底（日志标注 laser/baro），实飞验证 0.48→0.91m 定高成功；`tfmini_check.py` 可做接线自检。
- 双机环境采集，见 `docs/ENV.md`（Windows 台式机 = 实机调试；Mac = 文档/代码，不维护 SITL）。
- **RC/Offboard 调试工具**：`rc_monitor.py`（只读监视）、`hover_test.py`（1 米悬停，可 Ctrl+C / 遥控器接管）。端口写在文件顶部 `PORT`。
- **RC 开关配置手册**：`docs/RC_OFFBOARD_SETUP.md`（含参数表、验证清单、排查顺序）。
- **RC 与 Offboard 切换已验证可用**（遥控器与地面站代码可共存）。
- **视觉/安全骨架（ArUco 版，2026-10-27）**：
  - `vnav/` 包：`config` / `vision` / `link` / `safety` / `control` / `mission`
  - `run_visual_landing.py`：实飞降落 + `--bench` 手持验证
  - `vision_demo.py`：纯视觉演示（Mac 可跑）
  - `tools/make_aruco.py` + `markers/`：可打印标签，按物理尺寸出图
  - `tests/test_vision_smoke.py`：4 项冒烟测试，4/4 通过
  - 说明文档 `docs/PHASE4_ARCHITECTURE.md`

> 注意：这套骨架的检测器是 ArUco，**课程要的是 YOLOv8n 检测人**。
> 下游（解算→安全→控制→任务）可复用，检测器需要按 `docs/ROADMAP.md` 第四节做成可插拔。

## 正在做

- 2026-11-07 **坠机复盘**：上次是地面站数传延迟 + Ctrl+C 后降落指令没送达飞控；
  **不先解决失控保护不上桨**。参数与拆桨验证清单见 `docs/CRASH_AND_FAILSAFE.md`。
- 2026-11-07 起：**香橙派 5 Pro 上板 bring-up**。阶段 0/1 已完成：3 头 INT8 模型
  可检出人（conf 0.831），推理 18.3 FPS、端到端 13.7 FPS；下一步做 ONNX↔RKNN
  精度对照和 30 FPS 优化。见 `docs/RKNN.md`。
  - 系统镜像 `Orangepi5pro_1.0.6_ubuntu_jammy_desktop_xfce_linux5.10.160.img`
    （8.25GB，SHA256 `bcd25a16…c5a92`）已写卡并通过回读校验。
  - 首次开机成功；Windows 上 `ssh orangepi` 免密可用（IP 见 `docs/ENV.md` C 节）。

## 待确认（别当结论用）

1. `COM_RC_OVERRIDE` 在这版 PX4 里是否位掩码（bit1=OFFBOARD）？设 1 可能只对 AUTO 生效。
2. `COM_RC_IN_MODE` 当前值——之前"禁用遥控器"改的很可能就是它。
3. `RC_STICK_DZ` 默认是否已是 0.1。
4. 相机内参未标定（`calib.json` 还不存在），视觉测距目前是估算值。
   **注意**：SITL 里不适用——仿真的内参由 hfov 精确算出（`fx=270` @640），
   这是仿真唯一的"作弊"，不能当成实机精度。
5. ArUco 标签实际边长、安装朝向（画面顶部是否对机头）尚未实测确认。
6. **摄像头仍未采购**——视觉只能用笔记本摄像头、手机 IP Webcam、SITL 仿真
   或先用 USB UVC 摄像头验证；装机自主降落要等相机。
7. 香橙派上 **MAVSDK aarch64 已预检通过**（3.15.3 + server）；**5 Pro 排针 UART 定义**
   仍待验证；RKNN toolkit2 已在 WSL 24.04 跑通（3 头 INT8，18.3 FPS）。
8. **失控保护参数当前值未知**：`COM_OBL_RC_ACT`、`COM_OF_LOSS_T`、`COM_RC_OVERRIDE`、
   `NAV_RCL_ACT`。上电后用 QGC 读一遍并记录；目标见 `docs/CRASH_AND_FAILSAFE.md`。
9. **RKNN 精度已批量对照**：40 张最佳匹配 IoU **0.9899**（min 0.9757），
   40/40 检出；端到端 13.7 FPS，尚未优化到 30。

## 下一步

0. **上桨前先做失控保护地面验证**（拆桨，红线）：`COM_OBL_RC_ACT=Land`、
   `COM_OF_LOSS_T=1.0`、`COM_RC_OVERRIDE` 覆盖 Offboard；脚本杀掉后 2s 内
   飞控必须退出 Offboard 并进入 Land。见 `docs/CRASH_AND_FAILSAFE.md`。
1. **香橙派 5 Pro 阶段 1：RKNN**（已打通 3 头 INT8）：精度验收过（单图 IoU 0.9916，
   40 张 0.9899），推理 18.3 FPS / 端到端 13.7 FPS。下一步：后处理优化冲 30 FPS、
   板上视频链路验证。见 `docs/RKNN.md`。
2. **实机调试按 `docs/RC_OFFBOARD_SETUP.md` 走**。红线：清单第 5 项「Offboard 中打杆抢权」不通过就不上桨。
3. **三类课程场景的 SITL 版本**（不依赖采购，可并行）：静态已有；
   匀速给 actor 加轨迹；部分遮挡加挡板，验证 `target_stale_hold_s` / `_release_s` 分级。
4. **用 `gz_x500_lidar_down`（airframe 4016）复核高度闭环**——现在用的是 baro，
   真值比读数低约 0.12m；仿真里验高度最好用激光。
5. 相机到货后：张正友标定 → `calib.json` → 复测距离精度（**这一步才动实机**）。
6. 采购 USB 广角摄像头（几十块，UVC 免驱）→ 机载手持验证。

## 环境提醒

- Windows 用 conda `drone` 环境（Python 3.10 + mavsdk 3.15.3 + opencv 4.13），别用 base。
- Mac：`python3` = 系统 3.9.6，依赖在用户 site-packages；**不维护 SITL**，只写文档和跑纯视觉脚本。
- 串口约定：数传 57600 / USB 直连 115200，写在脚本顶部 `PORT`。
