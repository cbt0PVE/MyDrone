# 项目交接上下文（整段复制给新会话的 AI）

> 用法：新开对话，把下面整段贴过去。改完东西记得回仓库更新 `docs/STATUS.md`。

---

你接手的是一个无人机项目，仓库已在本机。**先做三件事**：`git pull`，读 `AGENTS.md`，读 `docs/STATUS.md`。然后再回答我。

## 项目是什么

**MyDrone**：250 级 FPV 穿越机（Holybro Pixhawk 4 + PX4），机载视觉目标追踪。它同时是一门课程的作业，课程要求交付**三类场景闭环**：静态目标、匀速移动、部分遮挡。

长期目标（不急）：在人群/干扰物中认出**特定的人**并追踪，之后再做无 GPS 避障巡航。课程交付先做「检测 + 跟踪 + 单目测距 + 速度闭环」，ReID 和避障是课外延伸。

技术栈：PX4、MAVSDK-Python（gRPC 版，3.15.x）、OpenCV、YOLOv8n；定高用北醒 TFmini-S；机载电脑规划香橙派 5 Pro（RK3588S，NPU 跑 RKNN）。

## 两台机器，分工固定

| 机器 | 干什么 | 不干什么 |
| --- | --- | --- |
| **macOS**（Apple Silicon） | 写文档、改代码、跑纯视觉脚本 | 不接飞控、不维护 SITL |
| **Windows 台式机** | 接飞控、调 PX4 参数、跑飞行脚本、GPU 训练 | — |

两边没有共享记忆，全靠仓库文件交接。**收工前更新 `docs/STATUS.md`**，接手时先读它。

## 仓库与同步规则

- 唯一远端：GitHub `cbt0PVE/MyDrone`，Gitee 已取消。
- 只在 `main` 上工作。开工 `git pull`，收工 `commit && push`。
- 大文件不进库：`*.pt / *.onnx / *.mp4 / datasets/ / runs/ / data/` 已在 `.gitignore`。
- `docs/` 写给 AI 的结论；`devlogs/` 人看的日志；`vnav/` 是控制包；根目录 `*.py` 是实物脚本。

## 当前进度（课程十周计划对照，见 `docs/ROADMAP.md`）

| 周 | 计划 | 状态 |
| --- | --- | --- |
| 1 | 文献与方案 | ✅ |
| 2 | SITL + Gazebo | ✅ 已在 WSL 验证（MAVSDK 1.1s 连上） |
| 3 | YOLOv8n 训练/量化/测速 | ✅ mAP@0.5 **0.7526**，66.3 FPS（4060） |
| 4 | 相机标定 + 像素→机体变换 | ⚠️ 变换代码完成，**缺实体相机和标定** |
| 6 | 硬件搭建 | ✅ 能飞 |
| 7 | 底层调试 + TFmini | ✅ TFmini 已装，激光定高实测成功（0.48→0.91m） |
| 8 | 视觉闭环 | ✅ 代码完成（YOLO+追踪），缺实机验证 |
| 5/9/10 | 中期验收 / 三类场景试飞 / 收尾 | ⬜ 未做 |

## 已完成的关键代码

| 文件 | 作用 |
| --- | --- |
| `hover_test.py` | 解锁→定高悬停；TFmini 激光优先、气压计兜底；Ctrl+C 安全降落 |
| `run_tracking.py` | YOLO 追踪入口：`--no-arm` 纯视觉 / `--bench` 手持 / 默认实飞 |
| `run_visual_landing.py` | ArUco 视觉降落（另一条路线，保留作对照） |
| `vnav/config.py` | 所有参数集中在这里 |
| `vnav/detectors.py` | YOLO 检测 + 单目测距（深度 = fy × 人高 / 框高） |
| `vnav/vision.py` | ArUco + PnP、坐标变换、PID、取图线程 |
| `vnav/link.py` | 连接 + 遥测缓存 + `height_m`（激光优先） |
| `vnav/safety.py` | 安全看门狗（丢目标/抢权/断链 → 悬停或交还） |
| `vnav/control.py` | Offboard 速度下发与退出 |
| `vnav/tracking.py` | 追踪状态机（保持距离 + 画面居中） |
| `tools/prepare_coco_person.py` | COCO val2017 → 单类 person 数据集 |
| `tools/train_yolo.py` | 训练 + 验证 + 导出 ONNX + 测 FPS |
| `tests/test_vision_smoke.py` | 5 项冒烟测试，不接硬件可跑 |
| `tfmini_check.py` / `rc_monitor.py` | 传感器与链路自检 |

## 必须知道的坑（都踩过了）

1. **PX4 这版没有 `EKF2_HGT_REF` 和 `EKF2_RNG_CTRL`**（1.15+ 高度源自动选择）。能调的是 `EKF2_RNG_NOISE`（0.10→0.05）、`EKF2_RNG_POS_Z`、`EKF2_RNG_A_HMAX`（默认 8m，超了不融合）。
2. **TFmini 贴地读数恒为 0.10**（量程下限），与"被挡住"无法区分。代码里 <0.15m 判无效，自动回退气压计。
3. **EKF 高度基准错了会拒绝激光**：估计 8.7m、激光 0.1m，差 8.6m 超出新息门限，直接被丢。上电时放平在地上、别拿手里，等 Ready。
4. **Ctrl+C 会销毁 gRPC 通道**，导致 `land()` 发不出去（Connection refused）。已改成"标志位 + 二次 Ctrl+C 才强退"。
5. **单类模型的 mAP 不能和 COCO 80 类榜单比**（0.75 vs 0.37 是因为任务简单了）。
6. **COCO 官方站单连接只有 0.5MB/s**，脚本已改多线程分段下载。
7. **SITL 必须在 WSL 终端里跑**，从脚本里调 `make` 会随父进程被杀。
8. **ArUco 与 YOLO 是两条路线**：ArUco 精度高但要已知尺寸标签；YOLO 通用但单目测距误差随距离线性放大（人高 ±12% 直接变成距离 ±12%）。
9. **`action.kill()` 是空中断桨**，任何脚本都不许拿它当收尾。
10. 课程第 2 周的 MAVROS 没接，用 MAVSDK 替代（功能等价）。

## 下一步优先级

1. **用 SITL 虚拟相机（`gz_x500_mono_cam`）跑一次完整闭环** —— 不依赖实体相机，验证检测→测距→追踪全链路。
2. 相机到货后：张正友标定 → `calib.json` → 复测距离精度。
3. 三类场景（静态/匀速/部分遮挡）各录一段，作为课程验收素材。
4. 香橙派到货后：`rknn-toolkit2` 转 INT8（需 100–200 张真实场景校准图），上板测 FPS。

## 安全红线

1. 不拆桨不飞；推进/姿态改动：拆桨 → 地面 → 低高度系留。
2. 禁止 `action.kill()` 当正常收尾，正常用 `land()`。
3. 改参数必须记：参数名 / 旧值 / 新值 / 依据 / 回退。
4. 脚本异常必须收敛到可预期安全状态（悬停或降落）。
5. Offboard 必须 ≥2Hz 持续发 setpoint。
6. 建议把 `COM_OBL_RC_ACT` 设为 Land —— 脚本挂了让飞机自己降落，而不是悬停等人。

## 常用命令

```powershell
# 自检
python tests/test_vision_smoke.py          # 5/5，不接硬件
python tfmini_check.py                     # 激光 vs 气压计
python rc_monitor.py                       # 只看模式/RC，零风险

# 飞行
python hover_test.py --no-arm              # 只发流，看高度源切换
python hover_test.py                       # 手托 1 米悬停
python run_tracking.py --no-arm            # 只跑视觉看距离
python run_tracking.py --bench             # 手持验证方向

# 训练（已跑完，重跑才需要）
python tools/prepare_coco_person.py
python tools/train_yolo.py
```

SITL 在 WSL 里：`cd ~/src/PX4-Autopilot && make px4_sitl gz_x500`，另一个 WSL 终端跑脚本加 `--port udp://:14540`。

## 现在请你

先读完那三份文件，然后告诉我：**你建议先做 SITL 相机闭环，还是先补相机标定？** 说明理由和风险。不要直接开始写代码。
