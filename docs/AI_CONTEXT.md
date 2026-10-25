# 项目交接上下文（整段复制给新会话的 AI）

> 用法：新开对话，把下面整段贴过去。改完东西记得回仓库更新 `docs/STATUS.md`。

---

你接手的是一个无人机项目，仓库已在本机。**先做三件事**：`git pull`，读 `AGENTS.md`，读 `docs/STATUS.md`。然后再回答我。

## 项目是什么

**MyDrone**：250 级 FPV 穿越机（Holybro Pixhawk 4 + PX4 固件），配机载视觉做目标追踪。当前核心课题是**让遥控器（PPM RC）与 MAVSDK Offboard 脚本安全共存**——平时遥控器兜底，拨特定开关才放行代码控制，飞手随时打杆或切回立刻抢回。

技术栈：PX4 Autopilot、MAVSDK-Python（gRPC 版，`import mavsdk`，3.15.x）、OpenCV，视觉后续演进到 YOLO / RKNN。垂直定高用北醒 TFmini-S（UART ToF），机载电脑规划香橙派 5 Pro（RK3588S，6 TOPS NPU）。

## 两台机器，分工固定

| 机器 | 干什么 | 不干什么 |
| --- | --- | --- |
| **macOS**（Apple Silicon，就是当前这台） | 写文档、维护日志、改代码（SITL 仅存档） | 不接实物飞控飞行、不维护仿真环境 |
| **Windows 台式机** | 接实物飞控（数传串口）、调 PX4 参数、跑硬件脚本、GPU 跑 YOLO | — |

两个环境之间**没有共享记忆**，全靠仓库文件交接。所以：离开一台机器前更新 `docs/STATUS.md`（到哪一步、下一步、坑），接手时先读它。不要假设另一台机器做过什么。

## 仓库与同步规则

- 唯一远端：**GitHub `cbt0PVE/MyDrone`**（`git@github.com:cbt0PVE/MyDrone.git`）。
- **Gitee 镜像已取消**，不要再往 Gitee 推，也不要提议恢复双远端。
- 只在 `main` 上工作，不搞 feature 分支。开工 `git pull`，收工 `git add -A && git commit && git push`。
- 大文件不进库：`*.mp4`、`*.pt`、`*.onnx`、`*.rknn` 已在 `.gitignore` 屏蔽。`yolov8n.pt` 和 `drone_test.mp4` 各机器自备。
- 仓库结构：`docs/` 是写给 AI 的结构化结论；`devlogs/` 是人向的开发日志（调研、踩坑、算法大纲、采购清单）；`src/` 是 SITL 与视觉代码；根目录 `*.py` 是接实物飞控的硬件脚本。

## 当前进度：阶段 0，链路与参数确认

已完成：
- 现有脚本审阅完毕，问题清单在 `docs/CODE_NOTES.md`（尚未改代码）。
- Windows 侧环境与工具链摸清并写入 `docs/ENV.md`。
- 仓库合并完成，两端统一到 GitHub。

进行中：
- **RC 通道映射**：在 QGC 的 Radio 页逐个拨动 6 个开关，记录哪个开关对应哪个通道、是两段还是三段。产出后才能给 `RC_MAP_OFFB_SW` 定值。这台 Mac 上没接飞控，所以这件事只能等 Windows 那边做。

待上机确认（**别当结论用**）：
1. `COM_RC_OVERRIDE` 在这版 PX4 里是否位掩码（bit1 = OFFBOARD）？只设 `1` 可能对 Offboard 不生效，要 `3`。
2. `COM_RC_IN_MODE` 当前值——之前"禁用遥控器才能解锁"改的很可能就是它。
3. `RC_STICK_DZ` 默认是否已是 0.1；若是，调到 0.15 收益很小。
4. 静置不碰杆时各通道数值是否稳在 1500（区分"死区问题"和"通道/信号问题"）。

计划路线见 `docs/ROADMAP.md`，参数清单见 `docs/PX4_PARAMS.md`。

## 已经踩过的坑（别重复）

- `takeoff.py` 的 `finally` 里无条件 `action.kill()`：那是空中紧急断桨，不是降落，异常时会直接掉机。
- 解锁顺序应是 **先发 setpoint ≥2Hz → `offboard.start()` → `arm()`**，现有代码反着来（先 arm 再 start），开 RC 时更容易被预检拒绝。
- `takeoff.py` 里 `BASE_THRUST=0.16` 注释写 18%、`MAX_THRUST=0.18` 注释写 20%，注释与值不一致。
- 姿态配平 `PITCH_TRIM/ROLL_TRIM` 是持续偏置，不该长期留在 setpoint 里。
- macOS 上 PX4 SITL 编译：`empy` 必须降到 3.3.4，否则 `RAW_OPT` 冲突；`pyyaml`/`pyros-genmsg` 有安装顺序坑。详见 `devlogs/无人机项目开发日志.md`。
- MAVSDK 别装 3.17+：那个包名已改成原生绑定，API 不兼容，锁 `mavsdk==3.15.3`。

## 安全红线

1. 不拆桨不飞。推进/姿态相关改动：拆桨上电 → SITL → 低高度系留 → 才真飞。
2. 禁止把 `action.kill()` 当正常收尾，正常用 `land()`。
3. 改飞行参数必须写清：参数名 / 旧值 / 新值 / 依据 / 回退。
4. 脚本异常必须进入可预期安全状态（悬停或降落），不能"什么都不做"或直接断桨。
5. SITL 能跑 ≠ 实机能飞：仿真没有 PPM 信号、磁罗盘干扰、电池压降。

## 写文档的约定

不写死本机路径和端口（`C:\Users\...`、`/Users/...`、`COM5`、`/dev/tty.*` 一律放 `docs/ENV.md`）；每条重要结论标 `已验证` / `待上机确认` / `推测`；中文文件名优先。

## 现在请你

先读完上面三份文件，然后告诉我：`docs/ENV.md` 里 Mac 那台还有哪些待填项、你建议我先补哪个。**先别写无人机控制代码**——RC 通道号还没定，写了也是白写。
