# 当前状态

> **每次收工前更新这里。** 这是跨机器唯一的"记忆"，不写就等于丢。
> 格式：写结论，不写过程流水账。

最后更新：2026-10-27 · Windows（阶段四代码落地）

## 阶段

两条线并行：

- **阶段四（课程主线，2026.10.16–11.30）**：视觉导航闭环 + 安全防护。代码已写完，待实机验证。
- **阶段 0（阻塞项）**：RC 与 Offboard 共存。这条不通，阶段四的实飞做不了。

## 已完成

- 通读早期三个脚本，结论见 `docs/CODE_NOTES.md`。
- 双机环境采集，见 `docs/ENV.md`（Windows 台式机 = 实机调试；Mac = 文档/代码，不维护 SITL）。
- **RC/Offboard 调试工具**：`rc_monitor.py`（只读监视）、`hover_test.py`（1 米悬停，可 Ctrl+C / 遥控器接管）。端口写在文件顶部 `PORT`。
- **RC 开关配置手册**：`docs/RC_OFFBOARD_SETUP.md`（含参数表、验证清单、排查顺序）。
- **阶段四代码**（2026-10-27）：
  - `vnav/` 包：`config` / `vision` / `link` / `safety` / `control` / `mission`
  - `run_visual_landing.py`：实飞降落 + `--bench` 手持验证
  - `vision_demo.py`：纯视觉演示（Mac 可跑）
  - `tests/test_vision_smoke.py`：4 项冒烟测试，当前 4/4 通过
  - 说明文档 `docs/PHASE4_ARCHITECTURE.md`

## 正在做

- 阶段四的**实机验证**（Windows）：先手持 `--bench` 验方向，再实飞降落。

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
