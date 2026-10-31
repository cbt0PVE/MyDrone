# SITL 相机视觉闭环（不依赖实体相机）

> 状态：取图链路 **已验证**（2026-10-31）｜检测+测距 **已验证**｜速度闭环 **见第七节**
>
> 目的：在相机还没买的情况下，用仿真把「检测 → 单目测距 → 保持距离 → 速度下发」
> 这条链路跑通，并且把**只能在空中暴露的 bug** 提前暴露掉（已经抓到两个）。

---

## 一、为什么不先做相机标定

标定是**被硬件阻塞**的短任务（相机到货后约 1 小时）；SITL 闭环是**不被阻塞**的长任务。
而且 SITL 逼出来的「取图源抽象」正是标定要用的同一层代码。
排序依据是关键路径，不是课程周次。

---

## 二、环境事实（WSL，已验证）

| 项 | 值 |
| --- | --- |
| 发行版 | Ubuntu 24.04 / WSL2 |
| Gazebo | `gz 8.11.0`（Harmonic），server-only 模式（`HEADLESS=1` → `gz sim -r -s`） |
| 机型 | airframe **4010 `gz_x500_mono_cam`** |
| 相机话题 | `/world/<world>/model/x500_mono_cam_0/link/camera_link/sensor/camera/image` |
| 图像 | **1280×960，RGB_INT8，30Hz** |
| Python 绑定 | `gz.transport13` **已装**（`/usr/lib/python3/dist-packages/gz/`） |
| `ros_gz_bridge` | **未装**，也用不上——Python 直连 Gazebo Transport 就够，不用赌 apt 网络 |

### 相机内参是精确已知的（仿真唯一的"作弊"）

`Tools/simulation/gz/models/mono_cam/model.sdf` 写死：

```xml
<horizontal_fov>1.74</horizontal_fov>       <!-- 约 99.7° -->
<image><width>1280</width><height>960</height></image>
<pose>.12 .03 .242 0 0 0</pose>             <!-- 相对 base_link -->
```

针孔模型下 `fx = (W/2) / tan(hfov/2)`：

| 分辨率 | fx = fy | cx, cy |
| --- | --- | --- |
| 1280×960 | **539.9** | 640, 480 |
| 640×480（本项目默认） | **270.0** | 320, 240 |

> ⚠️ **坑**：`config.py` 里没有标定文件时的兜底估算是 `0.9 × frame_width = 576`
> （640 宽时）。而仿真的真值是 **270**，差 **2.13 倍**。如果直接拿兜底值跑 SITL，
> 2.5m 的目标会被算成 5.3m，追踪状态机会一路往前冲。
> 现在 `load_camera_matrix()` 对 Gazebo 源走精确计算分支（`vnav/config.py`）。

> ⚠️ **坑**：相机装在 `base_link` 的 **+0.12m 前 / +0.03m 右 / +0.242m 上**，
> 不在机体原点。`estimate_from_bbox()` 假设相机在原点，这个杆臂在 2.5m 处
> 带来约 4.8% 的距离偏置。仿真里杆臂精确已知，可以量化；真机上还得拿尺子量。

---

## 三、跑起来

```bash
# 一次性接好资产（下载行人模型 + 把世界/模型链进 PX4 的资源目录，可逆）
bash sim/setup.sh

# 一键闭环：起 SITL → 等世界就绪 → 跑追踪 → 收尾
bash sim/run.sh                     # 默认跑 25 秒后自动降落
bash sim/run.sh --duration 60       # 自定义
bash sim/run.sh --no-arm            # 只跑视觉，看距离输出
```

`sim/setup.sh --clean` 拆除链接。

**必须整段在同一个 WSL 会话里跑**，原因见第六节。

---

## 四、仿真世界：`sim/worlds/mydrone_track.sdf`

以 PX4 的 `default.sdf` 为底，加了一个行人：

- 模型：Gazebo Fuel `OpenRobotics/MaleVisitorPhone`（自带 `idle` / `walk` /
  `idle_to_walk` / `walk_to_idle` 四套动画，是 `<actor>` 而不是普通 `<model>`）
- 摆放：`<pose>6 0 0 0 0 3.14159</pose>` —— 正前方 6m，转身面对机头
- 模型文件下载到 `sim/assets/`（**不入库**，`sim/setup.sh` 自取；约 2.9MB）

实测（1280×960 抓帧）：

| 项 | 值 |
| --- | --- |
| YOLOv8n 单类人体权重置信度 | **0.884** |
| YOLO bbox 高 | 164 px |
| 反推模型真实身高 | 6.00 × 164 / 539.9 ≈ **1.82 m** |
| 按 1.70m 先验的距离估计 | 5.61 m（真值 6.00，误差 **−6.5%**） |

> 这组数说明：**仿真的单目测距误差全部来自"人高先验"**，因为 `fx` 和真值距离都是精确的。
> 实机上还要再叠加镜头畸变和标定误差——所以别把仿真的 −6.5% 当成实机精度。

---

## 五、代码改动（这一轮）

| 文件 | 改动 |
| --- | --- |
| `vnav/camera.py` | **新增**。取图源抽象：`LocalCamera` / `GazeboCamera` / `open_camera(cfg)` |
| `vnav/detectors.py` | **新增 `OnnxDetector`**：纯 onnxruntime 推理（letterbox→NMS），不需要 torch/ultralytics |
| `vnav/config.py` | 加 `gazebo_hfov_rad` 等字段、`apply_sitl_preset()`、Gazebo 精确内参分支 |
| `vnav/vision.py` | `VisionWorker.start()` 改用 `open_camera()`；**新增** `ned_climb_rate()` |
| `vnav/control.py` | **新增** `OffboardController.climb_to()`（自动起飞爬升） |
| `vnav/safety.py` | `check_ready(..., allow_disarmed=)`，给 SITL 自动起飞用 |
| `vnav/tracking.py` | 高度指令改用 `ned_climb_rate()`（**修符号 bug**，见下） |
| `run_tracking.py` | 新增 `--sitl` / `--auto-takeoff` / `--duration` |
| `sim/setup.sh`、`sim/run.sh`、`sim/worlds/` | 新增。仿真编排 |
| `tests/test_vision_smoke.py` | 加 `test_sitl_intrinsics` / `test_altitude_sign`（7/7） |

**为什么加 `climb_to()`**：`run_tracking.py` 原本假设"飞手已经起飞并切好 Offboard"，
SITL 里没人替我们干这件事。自动起飞只对仿真默认开启（`--sitl`），
实机仍要求人工起飞——这是安全红线，不是技术限制。

---

## 六、这一轮踩到的坑（都记下来）

1. **世界名必须三处一致**：`<world name="X">`、文件名 `X.sdf`、环境变量 `PX4_GZ_WORLD=X`。
   PX4 的就绪判据是查 `gz service -i --service /world/$PX4_GZ_WORLD/scene/info`
   （见 `ROMFS/px4fmu_common/init.d-posix/px4-rc.gzsim:69`）。
   只改文件名不改 `<world name>`，PX4 会**永远卡在 `Waiting for Gazebo world...`**，
   而且日志里没有任何报错。`default.sdf` 能用只是因为三处恰好都叫 default。

2. **WSL 的后台进程会随会话一起消失**。`setsid nohup` 也没用——`wsl.exe` 一返回，
   会话结束，SITL 被带走，`make` 静悄悄退出（`[run_sitl] exited`，没有任何错误行）。
   所以「起仿真 + 干正事 + 收尾」必须写在**同一个脚本**里（`sim/run.sh` 就是这么来的）。
   顺带：`pxh` 控制台读到 stdin EOF 也会自己退出，所以后台跑要给 `</dev/null`。

3. **`gz.msgs10` 是个空壳命名空间**。`import gz.msgs10 as m; m.Image` 会
   `AttributeError`，必须 `from gz.msgs10 import image_pb2` 再用 `image_pb2.Image`。

4. **话题自动发现别用模糊匹配**。`gz topic -l | grep /sensor/camera` 会先命中
   `.../sensor/camera/camera_info`（不是图像）。现在只认以 `/image` 结尾的。

5. **Gazebo 的 Python `Node` 必须显式 `unsubscribe()`**，否则进程退出时
   回调线程还在跑、Node 被析构，直接 **segfault（退出码 139）**。
   `GazeboCamera.release()` 里已处理。

6. **`Select-Object`/管道提前关闭会让外部命令报 exit 1**。排查 WSL 命令"莫名失败"
   时先排除这个——它不是命令失败。

7. **收尾别用 `pkill -f` 宽匹配**。用宽匹配杀 `px4`/`gz sim` 会把 WSL 会话一起
   带走，下一次 `wsl.exe` 直接返回 `Wsl/Service/E_UNEXPECTED`（本次踩了两次，
   每次都要 `wsl --shutdown` 才能恢复）。现在 `sim/run.sh` 用 `setsid` 让
   `make` 自成进程组，只对该组发 TERM→KILL。

8. **`run_tracking.py` 此前从未被真正执行过**（所以 `IDLE` 的 `--no-arm`
   也跑不起来）。两处：没 `import asyncio`；把 `SafetyMonitor.check_ready`
   当模块函数调。冒烟测试只覆盖 `vnav/`，入口脚本一行没测到。
   已修，并补了符号回归测试。

---

## 七、已验证 / 待验证

**已验证（2026-10-31，WSL，`sim/run.sh`）**

- Gazebo 相机取帧（1280×960 RGB → 640×480 BGR），连续 540 帧无异常
- 内参由 hfov 精确推导，与手算一致（270.0 @ 640 宽）
- YOLO/ONNX 在仿真画面上检出人，`best.pt` conf 0.884
- 单目测距（静止、6.00m）：ONNX 路径 **6.02m（+0.3%）**
- 冒烟测试 **7/7**
- **速度闭环跑通**：解锁 → OFFBOARD → 爬升 → 逼近 → 保持 → 到点降落

一次完整运行（`bash sim/run.sh --duration 45`）的关键日志：

```text
[ 7.76s] [OK] 已解锁
[ 8.85s] [OK] 已进入 OFFBOARD
[31.61s] 状态 搜索目标 -> 跟踪中
[31.61s] [跟踪中] 高 0.85m(baro) | 前+5.85 右+0.08 | 指令 前+0.60
...
[7x.xs] [跟踪中] 高 1.00m(baro) | 前+2.50 右+0.00 | 指令 前+0.00   <- 收敛并保持
[76.32s] 到达设定时长 45s，准备降落
[76.34s] [OK] 已发送降落指令
[77.51s] 已退出 OFFBOARD，控制权交还
```

**收敛质量**：目标距离 2.50m，稳态估计值 2.43~2.51m（抖 ±0.04m）。

### 用 Gazebo 真值对照后才发现的两件事

拿 `gz model -m x500_mono_cam_0 -p` 的真实位姿和日志里的读数对齐，发现两个
**只有在仿真里才能白拿**的事实：

1. **气压计高度偏高约 +0.12m，而且滞后。**
   真实高度 6 秒就到 1.00m，但 baro 读数花了 23 秒才爬到 0.85m——一开始
   差点误判成"爬升太慢"。更关键的是闭环把 baro 拉到 1.0m 时，飞机的
   **真实高度只有 0.88m**。
   → 结论：SITL 没有 TFmini，用 baro 做高度闭环会把飞机压得偏低。
   实机（第 7 周已验证激光定高）不会有这个问题。**要在仿真里验高度闭环，
   换 `gz_x500_lidar_down`（airframe 4016）。**

2. **近距离单目测距系统性偏低约 7%。**
   真值 2.65m（人 x=6.00、机 x=3.35）时，估计值是 2.47m；而 6m 处只差 +0.3%。
   原因不是标定，而是针孔公式 `Z = fy·H/h` 假设"目标是一个与像平面平行的
   薄片、相机与目标中心同高"。相机装在机体上方 0.242m、又比人的中心低，
   近距离时这个几何近似误差会被放大。
   → 结论：**单目测距的误差随距离减小反而变大**，"保持距离"够用，
   但别指望用它做"精确停在某处"。

**待验证（下一步）**

- 用 `gz_x500_lidar_down` 复核高度闭环（排除 baro 偏差）
- 三类课程场景：静态（改 pose 的 x）/ 匀速（actor 的 walk 动画 + 轨迹）/
  部分遮挡（加一块移动挡板）
- 目标横向移动时的左右修正方向（现在是 ±0.02m，基本没被激励过）

---

## 八、给 macOS 的话

`sim/` 这套东西**只在 WSL 里跑**。Mac 上不维护 SITL，只改文档和代码；
`vnav/camera.py` 在没装 `gz.transport13` 的机器上只在**真的要用 Gazebo 源**时才报错，
`import vnav.camera` 本身是安全的（绑定是延迟导入的）。
