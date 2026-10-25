# 现有脚本审阅结论

> 只审阅，未改动任何代码（按"先初始化、不着急写"的要求）。

## 环境（详见 `docs/ENV.md`）

Windows 上用 conda `drone` 环境（Python 3.10 + mavsdk 3.15.3）；base 环境是 Python 3.13 + mavsdk 3.17.4，那个包已更名 `mavsdk-grpc`，不要用。

`mavsdk.offboard.Attitude` 签名已核对：`(roll_deg, pitch_deg, yaw_deg, thrust_value)`，与 `takeoff.py` 的传参顺序一致。
`System` 已确认提供 `offboard`、`action`、`param` 等插件。

## `connection.py` —— 基本没问题

- 端口硬编码 `serial://COM5:57600`，COM 号会随插拔变化，建议后续做成参数/环境变量。
- 只读了电池和模式，没有打印 `is_connected` 之后的 `telemetry.health()`，调试时建议加。
- USB 直连飞控时用 `serial://COMx`；走 UDP（SITL）用 `udp://:14540`。

## `takeoff.py` —— 能跑，但有 4 个需要修的地方

### ① `action.kill()` 放在 `finally` 里（最高风险）

```python
finally:
    await drone.action.kill()
```

- `kill` 是**空中紧急断桨**，不是降落。任何一步抛异常（包括飞行中途）都会直接掉机。
- 落地后用 `kill` 也没必要：正常流程应是 `land()` → 等 `is_armed == False` 自动上锁。
- 建议：`finally` 里只做 `offboard.stop()` + （若已落地）`disarm()`；保留 `kill` 作为 Ctrl+C 急停的**独立按键**，且要人在场。

### ② 解锁顺序反了

现在是：`arm()` → `set_attitude()` → `offboard.start()`。
PX4 推荐：**持续发 setpoint → `offboard.start()` → `arm()`**。在 RC 参与的场景下，先 arm 再切 Offboard 会额外触发预检/模式切换冲突，正是你现在遇到的"控不了"的一部分。

另外 `arm()` 失败被 `except` 吞掉后仍继续往下走，脚本会在"未解锁"状态下发 setpoint、打印"起飞中"，日志会骗人。建议 `arm()` 失败就 `return`。

### ③ 推力限幅的逻辑矛盾

```python
BASE_THRUST = 0.16   # 注释写 18%
MAX_THRUST  = 0.18   # 注释写 20%
```

- 注释和值不一致，容易误判。
- `MAX_THRUST=0.18` 对 250 级机是否够起飞，完全取决于推重比；靠"手托抬升"测出来的结果不能直接复用到真飞。
- 定高闭环 `KP_ALT=0.10` 且积分项缺失，气压计噪声下容易震荡；接 TFmini-S 后应换传感器并重调。

### ④ 姿态配平硬编码

`PITCH_TRIM=1.0° / ROLL_TRIM=-1.2°` 是**持续姿态偏置**，Offboard 全程都带着。这等价于给飞控一个恒定前倾/侧倾指令，会持续漂移。正确做法是调机体配平（重心/电机座）或用 `trim` 参数，而不是在 setpoint 里长期加偏置。若只是为了让手托测试不飘，应做成命令行开关，别留在默认路径。

### 其他

- 高度取 `telemetry.position().relative_altitude_m`（气压计），室内漂移大 —— 这正是要上 TFmini-S 的原因。
- 没有 `telemetry.health()` 预检、没有 `is_armed` 校验、没有 home 位置检查。
- 控制循环 10Hz 满足 ≥2Hz 要求，OK。

## `drone_track.py` —— PC 端验证用，没问题

- `model.track(..., show=True, save=True)` 会同时开窗和录盘，长时间跑磁盘涨得快。
- 后续上香橙派要换成 RKNN（`rknn_model_zoo` 的 yolov8 示例）+ 不用 `show`，并做 INT8 量化。
