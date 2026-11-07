# 飞行日志与飞行模式

> 2026-11-07 新增。目标：每次飞行都有**可读、可分析、体积小**的记录；
> 起飞前一条命令关掉 WiFi/蓝牙，减少对 2.4G 遥控的干扰。

---

## 一、日志格式

每一行都是：

```text
[级别][HH:MM:SS.mmm](消息 字段=值 字段=值 ...)
```

例子：

```text
[INFO][18:36:42.101](session_start session=track_20261107_183642_1234 text=logs/track_...log jsonl=logs/track_...jsonl)
[INFO][18:36:42.105](run_start app=run_tracking host=orangepi5pro python=3.10.12 port=serial:///dev/ttyS0:921600 camera=0 detector=yolo track_distance=2.5 hover_alt=1.0 control_hz=20.0)
[INFO][18:36:43.220](camera_ready camera=0 weights=runs/.../best.rknn)
[INFO][18:36:45.330](link_connected port=serial:///dev/ttyS0:921600)
[INFO][18:36:46.010](offboard_enter)
[STATE][18:36:46.510](phase=TRACK mode=OFFBOARD armed=1 alt=1.02 alt_src=laser baro=1.14 att=0.4/-0.2/87.3 vel=0.01/-0.02/0.00 batt=92 rc=98 link=0.04 sats=12 cmd=0.00/0.00/-0.10 tgt=2.51/0.03/0.01 tgt_age=0.05 tgt_id=3 tgt_conf=0.88 fps=27.3 temp=43.2)
[WARN][18:36:48.120](safety_hold reason=target_lost age=0.62)
[INFO][18:36:49.500](phase_change old=SEARCH new=TRACK)
[INFO][18:37:10.000](land_requested)
[INFO][18:37:12.000](session_end duration_s=29.9)
```

### 级别

| 级别 | 用途 |
| --- | --- |
| `DEBUG` | 排查用，默认很少 |
| `INFO` | 事件：连接、解锁、切 Offboard、降落 |
| `STATE` | 固定频率的状态快照（默认 2Hz） |
| `WARN` | 丢目标、自检失败、人工接管 |
| `ERROR` | 异常、中止、解锁失败 |

> 为什么状态只写 2Hz：20Hz 写盘会把日志变成噪声，10 分钟就几十万行，
> 而且对分析姿态/距离曲线没有额外价值。需要更密可以在命令行调 `--log-hz`。

---

## 二、文件

每次运行生成两个同名文件，放在 `logs/`：

```text
logs/track_20261107_183642_1234.log    # 人看，和终端输出一致
logs/track_20261107_183642_1234.jsonl  # 每行一个 JSON，画曲线用
```

- `logs/` 已加入 `.gitignore`，不会进仓库。
- 文件名带 PID，同一秒跑两次也不会覆盖。
- 一次飞行 = 一对文件；`session_start` / `session_end` 包住整段。

从板子取回日志：

```powershell
scp -r orangepi:~/logs .
```

---

## 三、STATE 字段

| 字段 | 含义 | 单位/取值 |
| --- | --- | --- |
| `phase` | 任务阶段 | `PREFLIGHT` / `SEARCH` / `TRACK` / `RELEASED` / `DONE` / `VISUAL` |
| `mode` | 飞控模式 | `OFFBOARD` / `POSCTL` / … |
| `armed` | 是否解锁 | 1/0 |
| `alt` | 控制用高度（激光优先） | m |
| `alt_src` | 高度源 | `laser` / `baro` |
| `baro` | 气压计相对高度 | m（和 `alt` 对照可看激光偏差） |
| `att` | 姿态 roll/pitch/yaw | 度，`0.4/-0.2/87.3` |
| `vel` | 实际速度 N/E/D | m/s |
| `batt` | 电量 | % |
| `rc` | 遥控信号强度 | %；拿不到为 `-` |
| `link` | 遥测距上次更新的时间 | s；越大越危险 |
| `sats` | GPS 卫星数 | 个；室内为 `-` 或 0 |
| `lat` / `lon` | 经纬度 | 度；无定位时省略 |
| `cmd` | 最近一次 NED 速度指令 | m/s；和 `vel` 对照看跟踪效果 |
| `tgt` | 目标前/右/下 | m，机体系 |
| `tgt_age` | 检测结果距现在 | s |
| `tgt_id` | 跟踪 ID | ByteTrack ID；ONNX 无跟踪器时为 -1 |
| `tgt_conf` | 检测置信度 | 0–1 |
| `fps` | 视觉实际帧率 | 帧/s |
| `temp` | SoC 温度 | °C（Linux 才有） |

---

## 四、事件名

| 事件 | 含义 |
| --- | --- |
| `session_start` / `session_end` | 日志会话开始/结束 |
| `run_start` | 本次运行的配置快照 |
| `camera_ready` | 相机启动成功 |
| `link_connected` | MAVSDK 连上飞控 |
| `self_check_ok` / `self_check_failed` | 起飞前自检 |
| `armed` | 已解锁 |
| `offboard_enter` | 已进入 OFFBOARD |
| `takeoff_done` | 自动爬升结束（`reached=1` 表示到达） |
| `mission_start` / `mission_end` | 追踪任务开始/结束 |
| `phase_change` | SEARCH/TRACK 切换 |
| `safety_hold` | 丢目标，原地悬停 |
| `safety_release` | 交还人工 |
| `safety_abort` | 中止并降落 |
| `land_requested` | 已发降落指令 |
| `offboard_release` | 已退出 Offboard |
| `arm_failed` / `arm_timeout` | 解锁失败/超时 |
| `exception` | 未捕获异常（带 `error=`） |

---

## 五、怎么用

### 运行

```bash
# 默认写 logs/，状态 2Hz
python run_tracking.py

# 自定义目录/频率
python run_tracking.py --log-dir /home/orangepi/flight_logs --log-hz 5

# 不写文件，只打印（台架快速试）
python run_tracking.py --no-log
```

### 看

```bash
tail -f logs/track_*.log                 # 实时跟
grep '\[WARN\]\|\[ERROR\]' logs/*.log    # 只看异常
grep '\[STATE\]' logs/*.log | tail -20   # 看最近状态
```

### 分析（Python）

```python
import pandas as pd

df = pd.read_json("logs/track_20261107_183642_1234.jsonl", lines=True)
state = df[df.level == "STATE"]
print(state[["t", "alt", "att", "tgt", "batt"]].describe())
```

或者直接用 `jq`：

```bash
jq -c 'select(.level=="STATE") | {t,alt,att,tgt}' logs/*.jsonl | head
```

---

## 六、飞行模式脚本

`tools/flight_mode.sh`：起飞前关 WiFi/蓝牙，降落后恢复。

```bash
bash flight_mode.sh status   # 只看状态，不改
bash flight_mode.sh off      # 关 WiFi + 蓝牙（WiFi SSH 会断，正常）
bash flight_mode.sh on       # 恢复（本地终端或插网线跑）
```

它只动 WiFi/蓝牙，**不动飞控 UART、不动视觉程序**。

> `off` 会断掉 WiFi SSH，这是预期行为。建议：
> - 起飞前在板子本地终端跑 `off`；或
> - 接受 SSH 断开，直接飞；降落后重启板子，WiFi 自动连回来。

---

## 七、设计取舍

1. **文本 + JSONL 双写**：人看文本，画图用 JSONL；字段值在文本里压缩，在 JSONL 里保留原始数值。
2. **状态 2Hz、事件立即**：既不会淹没关键事件，也不会漏掉姿态趋势。
3. **不加第三方依赖**：只用标准库，香橙派上不需要装 pandas 也能写日志。
4. **线程安全**：视觉线程 + 控制协程 + 状态任务共用一个锁。
5. **字段名短**：`att`/`vel`/`cmd`/`tgt` 是固定顺序的元组，文本短、JSON 里是数组。

---

## 八、当前接入范围

- ✅ `run_tracking.py`：完整接入（配置、事件、2Hz 状态、异常、退出）
- ⬜ `hover_test.py`：还没接；它有自己的简化状态，下一步可以复用 `FlightLogger`
- ⬜ `run_visual_landing.py`：还没接

> 先保证主任务（追踪）的日志完整；另外两个脚本后续按同样方式接。
