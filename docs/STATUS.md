# 当前状态

> **每次收工前更新这里。** 这是跨机器唯一的"记忆"，不写就等于丢。
> 格式：写结论，不写过程流水账。

最后更新：2026-10-27 · Windows（阶段四代码落地）

## 阶段

按课程十周计划推进（逐周对照见 `docs/ROADMAP.md`）：

- **硬件超前**：装机完成、能飞，**RC 与 Offboard 已可切换（已验证）**。
- **仿真已补齐**：WSL 里的 PX4 SITL + Gazebo Harmonic 实测可用，MAVSDK 1.1s 连上（见 `docs/SITL_GUIDE.md`）。
- **当前该做第 3 周**：YOLOv8n 的数据集 / 训练 / 量化 / 测耗时。
- **缺口**：TFmini-S 未装；相机与机载电脑未采购；相机未标定。

## 已完成

- 通读早期三个脚本，结论见 `docs/CODE_NOTES.md`。
- 2026-10-27 实测 WSL 仿真链路：PX4 SITL（`gz_x500`）启动成功，MAVSDK `udp://:14540` 1.1 秒连上，见 `docs/SITL_GUIDE.md`。
- 2026-10-27 **第 3 周训练完成**：YOLOv8n 单类 person，mAP@0.5 = **0.7526**，mAP@0.5:0.95 = 0.4983；4060 上 66.3 FPS（PyTorch）/ 45.7 FPS（ONNX-CPU）。产物与图表见 `docs/WEEK3_RESULTS.md`。
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

- 第 3 周：YOLOv8n 数据集与训练（不依赖无人机/相机采购）。

## 待确认（别当结论用）

1. `COM_RC_OVERRIDE` 在这版 PX4 里是否位掩码（bit1=OFFBOARD）？设 1 可能只对 AUTO 生效。
2. `COM_RC_IN_MODE` 当前值——之前"禁用遥控器"改的很可能就是它。
3. `RC_STICK_DZ` 默认是否已是 0.1。
4. 相机内参未标定（`calib.json` 还不存在），视觉测距目前是估算值。
5. ArUco 标签实际边长、安装朝向（画面顶部是否对机头）尚未实测确认。
6. **摄像头与机载电脑均未采购**——视觉只能用笔记本摄像头或手机 IP Webcam 验证，装机自主降落要等硬件。

## 下一步

0. **实机调试按 `docs/RC_OFFBOARD_SETUP.md` 走**。红线：清单第 5 项「Offboard 中打杆抢权」不通过就不上桨。
1. 完成 RC 通道映射，填进 `docs/PX4_PARAMS.md` 与手册第 2 节。
2. 生成并打印标签：`python tools/make_aruco.py`，量黑框边长，改 `marker_size_m`。
3. 用笔记本摄像头验算法：`python vision_demo.py --marker-size 0.12`。
4. 手机 IP Webcam 当摄像头，手持 `python run_visual_landing.py --bench --camera "http://..."`：验正负号 + 验"丢目标 2 秒交还控制权"。
5. 采购 USB 广角摄像头（几十块，UVC 免驱）→ 再做真正的机载手持验证。
6. 张正友标定 → `calib.json` → 复测距离精度。
7. 以上都过、且机载电脑到位，再实飞 `python run_visual_landing.py`。

## 环境提醒

- Windows 用 conda `drone` 环境（Python 3.10 + mavsdk 3.15.3 + opencv 4.13），别用 base。
- Mac：`python3` = 系统 3.9.6，依赖在用户 site-packages；**不维护 SITL**，只写文档和跑纯视觉脚本。
- 串口约定：数传 57600 / USB 直连 115200，写在脚本顶部 `PORT`。
