# 路线图

## 阶段 0：链路与参数（进行中，无代码）

- [ ] 完成 6 个开关 ↔ 通道号映射，记录两段/三段。
- [ ] 核对 `COM_RC_IN_MODE`、`COM_RC_OVERRIDE`（位掩码含义）、`NAV_RCL_ACT`、`COM_OBL_RC_ACT`。
- [ ] 按 `docs/PX4_PARAMS.md` 清单过一遍，记录旧值/新值/回退。

## 阶段 1：安全骨架（拆桨 + SITL）

- [ ] 修 `takeoff.py` 的 `kill()` 与解锁顺序（见 `docs/CODE_NOTES.md`）。
- [ ] 抽公共层：连接/端口配置、`health()` 预检、状态回调日志。
- [ ] SITL（`udp://:14540`）跑通起飞→悬停→降落，无 RC 依赖。
- [ ] 加 RC 通道只读监视脚本（QGC 之外的实时数值打印），便于判断抢权/开关状态。

## 阶段 2：遥控器共存验证（拆桨 → 系留）

- [ ] `RC_MAP_OFFB_SW` 生效验证：开关 B 允许位才可切 Offboard。
- [ ] 打杆抢权验证（Offboard 下）。
- [ ] 拔接收机模拟 RC 丢失，确认失效保护动作。

## 阶段 3：TFmini-S 定高

- [ ] 接线与 PX4 串口参数配置（`SENS_TFMINI_CFG` 及对应 `SER_*` 端口），确认 `distance_sensor` 数据进入 EKF。
- [ ] MAVSDK 改读 `telemetry.distance_sensor()`，重做高度环（建议 PI + 输出限幅）。
- [ ] 低高度（<30cm）系留验证定高稳定性。

## 阶段 4：机载视觉（香橙派 5 Pro）

- [ ] 系统/供电/串口直连（`serial:///dev/ttyAMA0` 或 USB）。
- [ ] YOLOv8n → RKNN INT8，测帧率与精度损失。
- [ ] 视觉结果转 NED setpoint，与阶段 3 的高度环合成。

## 待定问题

1. Pixhawk 4 的 PPM 输入是否经过 IO 协处理器？PPM 通道数上限是否会丢通道（影响 6 开关）。
2. 250 级机在 `MAX_THRUST` 限制下的实际推重比 —— 需拆桨电机测试 + 台架测力。
3. Offboard 与 RC 抢权同时发生时，PX4 的优先级是否会让模式在 `OFFBOARD`/`POSCTL` 间抖动。
