# 阶段四代码说明（2026.10.16 – 11.30）

对应 `devlogs/软件和算法详细大纲.md` 的阶段四：

| 大纲要求 | 本周代码 | 状态 |
| --- | --- | --- |
| 安全防护机制：丢目标/程序异常时自动释放控制权 | `vnav/safety.py` + `vnav/control.py` | 已实现 |
| 手持闭环验证：不装桨，验证控制方向正负 | `run_visual_landing.py --bench` | 已实现，待实测 |
| 实机自主降落/追踪大考 | `run_visual_landing.py` | 已实现，待实测 |

---

## 一、代码地图

```text
vnav/
├── config.py     所有参数（端口、相机、PID、安全阈值），改参数只改这里
├── vision.py     ArUco 检测 / PnP 位姿 / 视觉 PID / 后台取图线程
├── link.py       MAVSDK 连接 + 遥测状态缓存
├── safety.py     安全看门狗（纯函数式判定，可单独测试）
├── control.py    Offboard 速度指令下发与退出
└── mission.py    视觉追踪降落状态机

run_visual_landing.py   实机入口（--bench 手持验证）
vision_demo.py          纯视觉演示，Mac 上可直接跑
tests/test_vision_smoke.py   冒烟测试，不接硬件
```

分层理由：**视觉、安全、控制、任务四件事互不依赖**。安全层不 import MAVSDK 之外的东西，所以能被单元测试；视觉层不 import 飞控，所以能在 Mac 上单独跑。以后换飞控或换算法，只动一层。

---

## 二、数据流

```text
摄像头 ──(线程)──> ArUco 检测 ──> PnP 位姿 ──> 机体坐标 (前, 右, 下)
                                                  │
                                                  ▼
                                        ┌── 安全看门狗 ──┐
                                        │  丢目标？抢权？  │
                                        └────────┬───────┘
                                   正常          │        异常
                                    ▼            │         ▼
                              视觉 PID ──────────┘    原地悬停 / 交还人工
                                    │
                                    ▼
                          机体系速度 ──(按偏航旋转)──> NED 速度
                                    │
                                    ▼
                          MAVSDK set_velocity_ned ──> PX4 Offboard
```

关键点：**控制循环（20Hz）和视觉（约 30Hz）是两条独立的时间线**。控制循环永远用"最新一次的识别结果"，即使这一轮没识别到也不阻塞——否则画面一卡，飞控就因为收不到 setpoint 触发 Offboard 丢失保护。

---

## 三、坐标系（最容易写错的地方）

| 坐标系 | x | y | z | 谁用 |
| --- | --- | --- | --- | --- |
| 相机（OpenCV） | 右 | 下 | 镜头正前方 | PnP 输出 |
| 机体 FRD | 前 | 右 | 下 | 视觉误差、PID |
| 世界 NED | 北 | 东 | 下 | MAVSDK 指令 |

相机朝下安装、画面顶部对机头时：

```
机体前向 = -相机 y        （画面往下 = 机尾方向）
机体右向 =  相机 x
机体下向 =  相机 z
```

这套约定写在 `vnav/vision.py: camera_to_body()` 的 `signs` 参数里。**装法一变，只需要改这一处**，不要在别处分别取反。

### 手持验证怎么验

1. 不装桨，人托着飞机离地 30cm 左右（**不要让飞控以为自己在飞**，所以 `--bench` 模式下垂直速度恒为 0）。
2. 把标签放在飞机正下方，运行 `--bench`。
3. 观察终端里 `指令 前+xx 右+xx`：
   - 把飞机往**左**移（标签相对飞机向右），指令的"右"应为**正**；
   - 把飞机往**前**移（标签相对飞机向后，即画面往下），指令的"前"应为**负**。
4. 符号反了，就改 `camera_to_body` 的 `signs`，然后 `python tests/test_vision_smoke.py` 会立刻发现回归。

这一步就是大纲里说的"向左晃动时电机自动加速往右对抗，证明正负方向正确"。

---

## 四、安全矩阵

`vnav/safety.py` 的判定优先级，**命中即返回，不再往下判断**：

| 优先级 | 条件 | 动作 | 为什么这个顺序 |
| --- | --- | --- | --- |
| 1 | 遥测断流 > 1s | 中止 | 已经不知道飞机什么状态了 |
| 2 | 未解锁 | 中止 | 任务没有前提 |
| 3 | 离开 OFFBOARD | 交还 | 遥控器抢权永远最高优先 |
| 4 | 电量 < 20% | 中止 | 保命 |
| 5 | 丢目标 > 2s | 交还 | 视觉不可信，让人来 |
| 6 | 丢目标 > 0.6s | 悬停 | 短暂丢帧，等等看 |
| 7 | 其他 | 继续 | — |

"交还"= 停止发 setpoint + `offboard.stop()`，之后完全听遥控器。**一旦交还就不会再抢回来**（`SafetyMonitor.released` 置位），避免和飞手来回拉锯。

### 程序异常

`run_visual_landing.py` 的 `finally` 里依次：停视觉 → 退出 Offboard → 停遥测。**没有 `kill()`**。异常时飞控会按 `COM_OBL_RC_ACT` 自己处置（建议设为 Position 或 Hold）。

---

## 五、状态机

```text
SEARCH ──识别到标签──> ALIGN ──水平误差<10cm 且保持1s──> DESCEND
   ▲                      │                                   │
   │                      │ 丢目标                            │ 高度<=0.35m
   └──────────────────────┴───────────────────────────────────▼
                                                          LANDING
                                                        （PX4 自己落地）
```

- `--bench` 模式下 `ALIGN` 之后不再进入 `DESCEND`，只持续对准，方便人看指令符号。
- 任何状态命中安全矩阵都会直接跳出，不走状态机。

---

## 六、参数（`vnav/config.py`）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `port` | `serial://COM5:57600` | 数传 57600 / USB 115200 |
| `control_hz` | 20 | 控制循环频率，PX4 要求 >2Hz |
| `marker_size_m` | 0.12 | **必须拿尺子量实际标签边长** |
| `hover_alt_m` | 1.0 | 追踪时保持的高度 |
| `descend_stop_alt_m` | 0.35 | 降到这个高度交给 PX4 |
| `descend_rate_mps` | 0.25 | 下降速度 |
| `align_tolerance_m` | 0.10 | 水平对准容差 |
| `kp/ki/kd_xy` | 0.8 / 0.05 / 0.15 | 视觉 PID，输出单位 m/s |
| `max_speed_mps` | 0.6 | 水平速度上限 |
| `target_stale_hold_s` | 0.6 | 丢目标多久开始悬停 |
| `target_stale_release_s` | 2.0 | 丢目标多久交还人工 |

相机标定：把张正友标定的结果存成 `calib.json`

```json
{"camera_matrix": [fx,0,cx, 0,fy,cy, 0,0,1], "dist_coeffs": [k1,k2,p1,p2,k3]}
```

没有标定文件时会用估算内参，**距离会有明显偏差**，只适合验证方向，不适合精确降落。

---

## 七、怎么跑

### Mac（只读代码 / 写文档 / 纯视觉）

```bash
pip install opencv-python numpy
python tests/test_vision_smoke.py     # 不接硬件，验证算法逻辑
python vision_demo.py                 # 接摄像头看识别效果
```

### Windows（实机）

```powershell
# 1. 手持验证（不装桨！）
python run_visual_landing.py --bench

# 2. 实飞：飞手手动起飞到 1m 以上并在 Offboard 允许位
python run_visual_landing.py

# 3. 只看视觉
python vision_demo.py --marker-size 0.12
```

---

## 八、本周验收标准

- [ ] `tests/test_vision_smoke.py` 全绿（现在 4/4）
- [ ] `vision_demo.py` 能在 0.5–2m 内稳定识别、距离误差 < 20%（标定后 < 10%）
- [ ] 手持 `--bench`：左右/前后晃动时指令符号正确
- [ ] 手持 `--bench`：遮挡标签 2 秒以上，脚本打印"交还控制权"并退出 Offboard
- [ ] 打杆/拨开关能立刻触发交还，且脚本不会再抢回
- [ ] 以上都过，才允许进入实飞降落

---

## 九、已知限制

1. **高度用的是气压计**（`relative_altitude_m`），室内漂移大。TFmini-S 接上后应改读 `telemetry.distance_sensor()`，`config.py` 里预留了 `descend_stop_alt_m` 但没有接激光。
2. **单目 PnP 在标签倾斜时误差变大**，且标签必须完整出现在画面里。
3. **没有做标签 ID 过滤**，画面里多个标签时取离画面中心最近的一个。
4. **没有做偏航对准**：`Detection.yaw_deg` 已经算出来了，但状态机还没用，目前默认机头方向不重要。
5. **没接机载电脑**，视觉还在本机 USB 摄像头上跑；上香橙派后要换成 CSI 相机 + RKNN。
