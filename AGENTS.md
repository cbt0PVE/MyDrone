# MyDrone · 250 级 FPV 穿越机 + 机载视觉

> AI 协作者的入口文件。顺序：本文件 → `docs/STATUS.md`（当前进度）→ 相关文档。

## 一句话背景

Holybro Pixhawk 4 + PX4，250 级穿越机，配机载视觉做目标追踪。当前核心课题：让 **遥控器（PPM RC）与 MAVSDK Offboard 脚本安全共存**——平时遥控器兜底，拨开关才放行代码控制，飞手随时打杆/切回抢回。

## 仓库结构

```text
MyDrone/
├── AGENTS.md      # 本文件：AI 协作入口与规则
├── docs/          # 写给 AI 的结构化结论
├── devlogs/       # 人类向开发日志：调研、踩坑、算法大纲、采购清单
├── image/         # 文档配图
├── src/           # 仿真/视觉源码：test_mavsdk.py、test_opencv.py、main_tracker*.py
├── sim/           # SITL 仿真：setup.sh（资产+建链）、run.sh（起仿真跑闭环）、worlds/
├── vnav/          # 视觉导航控制包：config / camera / vision / link / safety / control / mission
├── tools/         # 数据集与模型工具：make_aruco / prepare_coco_person / train_yolo
├── tests/         # 冒烟测试（不接硬件也能跑）
└── *.py           # 实物脚本：connection / takeoff / drone_track / hover_test / rc_monitor
```

- `devlogs/` 是**过程记录**（人看）；`docs/` 是**结论沉淀**（AI 看）。两边都保留，不互相替代。
- `src/` 面向 SITL 与视觉；根目录脚本面向实物飞控（串口数传）。

## 双机器分工（没有共享记忆，靠文件交接）

| 机器 | 用途 |
| --- | --- |
| **macOS**（Apple Silicon） | 写文档、维护日志、改代码（SITL 环境仅存档，不维护） |
| **Windows 台式机** | 接实物飞控（数传/串口）、调 PX4 参数、跑硬件脚本、GPU 跑 YOLO |

### 切换机器的固定动作

- **收工前**：更新 `docs/STATUS.md`（到哪一步、下一步、坑/未决）。不写就等于丢记忆。
- **接手时**：`git pull` → 读 `AGENTS.md` → 读 `docs/STATUS.md` → 再看相关文档。不要假设另一台做过什么。
- **新开对话**：直接把 `docs/AI_CONTEXT.md` 整段贴过去，那是自包含的交接说明。

### 写文档的约定

- **不写死本机路径/端口**。`C:\Users\...`、`/Users/...`、`COM5`、`/dev/tty.*` 一律放 `docs/ENV.md`，正文用中性说法。
- 每条重要结论标状态：`已验证` / `待上机确认` / `推测`。
- 参数改动记 **旧值 / 新值 / 依据 / 回退**。
- 中文文件名优先，和 `devlogs/` 保持一致。

## 硬性安全规则（写代码/给建议时必须遵守）

1. **不拆桨不飞**。推进/姿态相关改动：拆桨上电 → SITL → 低高度系留 → 才真飞。
2. **禁止把 `action.kill()` 当作正常降落/收尾**——它是空中紧急断桨。正常收尾 `land()` → 落地自动上锁。
3. **不改飞行参数不给理由**（按上面的记录格式）。
4. 脚本异常必须进入**可预期安全状态**（悬停/降落），不能"什么都不做"或"直接断桨"。
5. Offboard 必须保证 **≥2Hz** 持续发 setpoint，否则触发 Offboard 丢失保护。
6. **SITL 里能跑 ≠ 实机能飞**。仿真没有 PPM 信号、没有磁罗盘干扰、没有电池压降。

## 代码约定

- **端口写在文件顶部**：每个脚本顶部一个 `PORT` 常量（如 `"serial://COM5:57600"`），注释写清"数传 57600 / USB 直连 115200"，命令行 `--port` 可临时覆盖。**用户偏好直接改常量，不要写自动探测逻辑。**
- MAVSDK 用 gRPC 版（`import mavsdk`，3.15.x）。**不要**装 3.17+ 的 `mavsdk` 包——名字已改成原生绑定，API 不兼容。
- 视觉从 OpenCV（HSV 质心）向 YOLO/RKNN 演进，两套别混着改。

## 文档索引

- `docs/STATUS.md` —— **当前进度与下一步（收工必更新）**
- `docs/SITL_CAMERA.md` —— **SITL 相机视觉闭环**：怎么起、仿真内参怎么算、踩过的坑
- `docs/AI_CONTEXT.md` —— 自包含的交接上下文，新对话直接整段粘贴
- `docs/GIT_CHEATSHEET.md` —— 拉取/提交/推送与常见报错处理
- `docs/PROJECT_CONTEXT.md` —— 硬件、链路、痛点根因、方案、标准流程
- `docs/PX4_PARAMS.md` —— 参数清单、失控保护链路、RC 通道映射方法
- `docs/RC_OFFBOARD_SETUP.md` —— **实机调试手册**：RC 开关 + Offboard 共存完整操作流
- `docs/PHASE4_ARCHITECTURE.md` —— **阶段四代码说明**：坐标系、安全矩阵、状态机、验收标准
- `docs/CODE_NOTES.md` —— 现有脚本逐条审阅结论（含 4 个待修点）
- `docs/ROADMAP.md` —— 分阶段计划
- `docs/ENV.md` —— 两台机器的环境事实
