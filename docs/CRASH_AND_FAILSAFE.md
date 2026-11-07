# 坠机复盘与失控保护（2026-11 更新）

> 背景：上一次飞行用**地面站 + 数传**跑 Offboard，链路延迟高；Ctrl+C 后
> 降落/停止指令没有送到飞控，飞机继续按旧指令飞，最后坠机。
>
> 结论：**主因是控制链路 + 失控保护，不是"偏角"本身。**
> 固定配平（`PITCH_TRIM`/`ROLL_TRIM`）只是把前漂压住，掩盖了真正的问题。

---

## 一、事故链（推测，按现有信息）

```text
地面站 → 数传 57600 → 飞控
   ↑ 延迟高、带宽小
   20Hz Offboard setpoint 被延迟/堆积
        ↓
   控制环路相位滞后 → 越修越晃 / 前漂
        ↓
   操作者 Ctrl+C
        ↓
   脚本停止发 setpoint；land() 没送达（链路/通道问题）
        ↓
   PX4 等 COM_OF_LOSS_T 后退出 Offboard
        ↓
   COM_OBL_RC_ACT 当时不是 Land（可能 Hold/Position）
        ↓
   室内无 GPS / 无光流 → 位置保持不住 → 漂移/乱飞 → 坠机
```

关键点：**Offboard 是靠"持续收到 setpoint"活着的**。脚本一停，飞控必须有一个
明确的兜底动作；这个动作没配对，飞机就会在你控制之外。

---

## 二、先改这组参数（拆桨、上电、QGC 里改）

> 规则：每项记录 **旧值 / 新值 / 依据 / 回退**。不同 PX4 版本枚举数字可能不同，
> **以 QGC 参数页的描述为准**，下表给的是目标语义。

| 参数 | 目标 | 作用 | 备注 |
| --- | --- | --- | --- |
| `COM_OBL_ACT` | **Land** | Offboard 数据流丢失后的动作 | 与下面一条是两个触发源，都设 |
| `COM_OBL_RC_ACT` | **Land** | Offboard 中 RC 丢失后的动作 | 室内首选 Land，不要 Return |
| `COM_OF_LOSS_T` | **1.0 s** | 多久没 setpoint 判为 Offboard Loss | 默认通常 1.0 |
| `NAV_RCL_ACT` | **Land** | RC 链路丢失后的动作 | 室内别设 Return |
| `COM_RC_LOSS_T` | 0.5 s | RC 丢失判定时间 | 默认 |
| `COM_RC_OVERRIDE` | **3**（bit0+bit1） | 打杆抢权，含 OFFBOARD | 先看 QGC 描述确认位掩码 |
| `COM_RC_IN_MODE` | **0** | RC 输入启用 | 不要用"禁用 RC 检查"绕过 |
| `RC_MAP_OFFB_SW` | 开关 B 通道 | Offboard 允许开关 | 拨回即退出 |
| `RC_STICK_DZ` | 0.10 | 摇杆死区 | 默认通常已是 |
| `COM_DISARM_LAND` | 默认 | 落地后自动上锁 | 别调太小 |

改完**重启飞控**，再进下一节。

> **两个 "Offboard 退出动作" 别搞混：**
> - **数据流停**（脚本死了/SSH 断了/香橙派重启）→ `COM_OBL_ACT`
> - **RC 丢失**（遥控器关了/接收机断了）→ `COM_OBL_RC_ACT`
>
> PX4 不同版本可能只暴露其中一个，或默认值不同。在 QGC 参数页搜 `OBL`，
> 把能看到的都设成 **Land**，并在参数描述里确认语义。不要只设一个就以为万事大吉。

> 为什么 `COM_OBL_RC_ACT=Land` 是关键：脚本死了、SSH 断了、香橙派重启了，
> 飞控都会在 1 秒左右自己降落，而不是保持最后一个速度指令。

---

## 三、地面验证（拆桨！）

必须按顺序做完，任何一项不过都不许上桨。

### 1. 链路与模式

- [ ] RC 开机对频，QGC Radio 页所有通道回中 ≈1500
- [ ] `COM_RC_IN_MODE=0`，RC 校准通过
- [ ] 开关 B 拨到允许位，QGC 显示 OFFBOARD（需要 setpoint 流）
- [ ] 拨回常规位，模式立刻退出 OFFBOARD

### 2. 脚本退出 → 飞控自救

- [ ] 拆桨，接**机载香橙派**（不是地面站数传），跑 `hover_test.py` 或 `run_tracking.py`
- [ ] 进入 OFFBOARD 后，直接 **Ctrl+C / 拔 SSH / 杀进程**
- [ ] 2 秒内 QGC 应显示退出 OFFBOARD 并进入 **LAND**
- [ ] 如果仍是 OFFBOARD 或 HOLD：参数没生效，停下来查，不要飞

### 3. 打杆抢权

- [ ] OFFBOARD 中推杆超过阈值（约 30%）
- [ ] QGC 模式立刻退出 OFFBOARD，回到人工模式
- [ ] 松杆后不自动回到 OFFBOARD（脚本应停止发流）

### 4. RC 丢失

- [ ] OFFBOARD 中关掉遥控器（或拔接收机）
- [ ] 确认 `NAV_RCL_ACT` / `COM_OBL_RC_ACT` 的动作符合预期（Land）
- [ ] 重新对频后能正常接管

### 5. 日志确认

新日志会记录：

- `safety_hold` / `safety_release` / `safety_abort`
- `land_on_exit` / `land_on_exit_failed`
- `offboard_release`
- `rc=` / `link=` / `mode=` 状态

飞完把 `logs/*.jsonl` 拉回来，确认退出瞬间的模式变化。

---

## 四、为什么不再用固定配平

`takeoff.py` 里的：

```python
PITCH_TRIM = 1.0    # 正数抬机头，压前漂
ROLL_TRIM  = -1.2   # 往左拉回
```

它确实能让某一次悬停看起来"不飘"，但：

1. **掩盖重心偏移**：电池/相机位置变了，补丁就失效；
2. **掩盖加速度计零偏**：飞控以为"水平"是斜的，换个方向飞又偏；
3. **掩盖电机/桨推力不一致**：桨损、电机歪、ESC 没校准；
4. **掩盖链路延迟**：延迟造成的振荡，用固定角度去压，只会把问题推到另一个方向；
5. **不可泛化**：悬停、前飞、转弯、不同电量下需要的配平都不一样。

正确顺序：**先查重心 → 加速度计水平校准 → 罗盘 → 电机/桨 → RC 中位**，
确认机械和传感器没问题后，再做控制。`hover_test.py` 已经不做固定配平；
如果它还飘，说明问题在机械/传感器，不在"少一个偏角"。

---

## 五、控制必须放机上，不要用地面站数传跑 Offboard

| 方案 | 延迟 | 适合 |
| --- | --- | --- |
| 地面站 → 数传 57600 → Offboard | 高、抖动大 | ❌ 不适合飞 |
| 香橙派 → UART 921600 → Offboard | 低、稳定 | ✅ 目标方案 |
| 地面站 → 数传 → 只看 QGC | 只读，不影响控制 | ✅ 监控 |

- 香橙派接飞控 **TELEM2**，`SER_TEL2_BAUD=921600`，`MAV_1_MODE=Onboard`。
- 地面笔记本只开 QGC 看状态，**不要同时跑 `run_tracking.py` 发 Offboard**。
- 视觉/控制在香橙派本地跑，断网也不影响飞行。

---

## 六、代码侧已做的修正

| 文件 | 修正 |
| --- | --- |
| `vnav/control.py` | `start(yaw_deg)` 用**当前机头朝向**预热，不再写死 yaw=0 |
| `run_tracking.py` | 调用 `controller.start(state.yaw_deg)`；异常/中断时若仍握着 Offboard 且已解锁，先尝试 `land()` 再交还 |
| `run_visual_landing.py` | 同样传当前 yaw |
| `hover_test.py` | 新增姿态监听，所有 `Attitude(...)` 的 yaw 都用当前机头；修 `rc.is_available` |
| `takeoff.py` | 顶部加"旧脚本/固定配平"警告，**不要再拿来飞** |
| `vnav/link.py` | 修 `rc.is_available`（MAVSDK 3.15 字段名） |

> 注意：代码里的 `land()` 是"尽力而为"。如果链路已经断了，它发不出去；
> 真正兜底的是 PX4 的 `COM_OBL_RC_ACT=Land`。两者都要有。

---

## 七、下一次飞行的顺序（不许跳）

1. 拆桨，改参数，重启飞控
2. 地面按第三节 1–5 项验证
3. 装桨，**系留/低高度（≤0.5m）**，RC 全程在手，先手动 Stabilized/Altitude 悬停
4. 确认不飘（或飘的原因已定位），再试 `hover_test.py` 短时悬停
5. 最后才跑 `run_tracking.py` 视觉追踪
6. 全程看新日志：`mode / alt / att / vel / rc / link / land_on_exit`

---

## 八、待确认（下次上电时记录）

1. `COM_OBL_ACT` / `COM_OBL_RC_ACT` 当前值是多少？改成 Land 后 QGC 里显示的数字是几？
2. `COM_RC_OVERRIDE` 当前值？QGC 描述里 bit0/bit1 是否覆盖 OFFBOARD？
3. 上次 Ctrl+C 后 QGC 显示什么模式？Hold / Position / Offboard？
4. 上次用的是 `takeoff.py`（带固定配平）还是 `hover_test.py`？
5. 室内有没有 GPS / 光流？如果没有，Position/Hold 类兜底都会漂，Land 更可靠。
6. 坠机后是否换过桨/电机/机架？加速度计、罗盘是否重新校准？
