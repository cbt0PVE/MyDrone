# 香橙派 5 Pro 上板（RK3588S）· 分阶段验收

> 状态：**计划**（2026-11-07 板子到货，尚未开箱验证）
> 第一次用开发板、还没写过系统卡：先看 **`docs/ORANGEPI_FIRST_BOOT.md`**（零基础开箱，
> 从下镜像、写 SD 卡到 SSH 登录），做完再回来按本文档走。
> 目标：把已经跑通的 `vnav` 视觉闭环从地面电脑搬到机上，**不改变控制逻辑**，
> 只替换三样东西：取图源、推理后端、MAVLink 物理链路。
>
> 原则：**每一步都有可验证的产出，验不过不许进下一步。**
> 尤其：板子单独验 → 拆桨接飞控只读 → 地面 `--no-arm` → 系留 → 才真飞。

---

## 零、先确认型号

采购单写的是 **Orange Pi 5 Pro（RK3588S，6 TOPS NPU，3 核）**。
如果实际到手是 Orange Pi 5 / 5B，**镜像、排针 UART、供电接口都不一样**，先停下来核对丝印。

---

## 一、阶段 0：桌面验板（不接飞控）

### 做什么

1. **供电**：独立 5V/5A（官方推荐 5V/5A）。不要从飞控 5V 取电，不要用电脑 USB 口。
   上电前万用表量到 5.0–5.2V；RK3588S 峰值电流大，掉压会直接重启。
2. **散热**：铝散热片 + 风扇。没有散热片，NPU 跑几分钟就降频。
3. **系统**：官方 Ubuntu 22.04（Orange Pi 5 Pro 专用镜像）。先 `apt update && apt upgrade`。
4. **网络**：SSH 能连（有线优先；WiFi 建议 5GHz，见风险 6）。
5. **NPU 驱动**：确认内核带 rknpu，能看到版本。
6. **压力测试**：CPU/NPU 同时跑 10 分钟，看温度和是否降频。

### 命令

```bash
uname -a
cat /etc/os-release
dmesg | grep -i -E 'rknpu|npu'
cat /sys/kernel/debug/rknpu/version 2>/dev/null
ls /dev/rknpu* 2>/dev/null
free -h && lsblk
cat /sys/class/thermal/thermal_zone*/temp
```

### 验收

- [ ] SSH 连续 30 分钟不掉线
- [ ] `rknpu` 版本能读出来（没有就是镜像/内核不对，**先别往下走**）
- [ ] 满载 10 分钟温度 < 80°C，无重启、无降频日志
- [ ] 存储剩余 > 20GB（模型 + 数据集 + 日志）

---

## 二、阶段 1：RKNN 工具链（转换在 x86，推理在板上）

> **2026-11-07 进展**：已打通 3 头 INT8，板上 conf 0.831、推理 18.3 FPS、
> 端到端 13.7 FPS。版本坑、3 头转换和 `run_with_rknn.sh` 见 `docs/RKNN.md`。
> 下面的通用流程仍适用，但具体命令以 `docs/RKNN.md` 为准。

### 关键事实

**`rknn-toolkit2` 只能在 x86_64 Linux 上做模型转换，不能在板子上转。**
板子上只装 `rknn-toolkit-lite2` + `librknnrt`，负责推理。

所以分工是：

| 机器 | 装什么 | 干什么 |
| --- | --- | --- |
| Windows/WSL（x86） | `rknn-toolkit2`（conda py3.10 或 Docker 镜像） | ONNX → RKNN、量化、精度对照 |
| 香橙派 | `rknn-toolkit-lite2`、`librknnrt` | 跑 `.rknn` |

> 待验证：WSL 是 Ubuntu 24.04，官方主要支持 18.04/20.04/22.04。
> 优先用 Rockchip 的 Docker 镜像；用 conda py3.10 装 wheel 也可能行，但依赖容易打架。

### 转换流程

```python
from rknn.api import RKNN

rknn = RKNN(verbose=True)
rknn.config(
    mean_values=[[0, 0, 0]],
    std_values=[[255, 255, 255]],
    target_platform="rk3588",
)
rknn.load_onnx(model="best.onnx")
rknn.build(do_quantization=True, dataset="dataset.txt")  # 100–200 张，640×640
rknn.export_rknn("best.rknn")
```

- 输入模型：`runs/detect/runs/detect/coco_person/weights/best.onnx`
- 量化集：COCO val2017 里挑 100–200 张有人的图（**不要只用人脸/单人特写**）
- 若 INT8 掉点明显：先试 `do_quantization=False`（FP16）确认是量化问题，再调量化集
- 若 ONNX 加载报 opset 太高：用 ultralytics 重新导出 `opset=12`

### 板上推理

```bash
pip install rknn-toolkit-lite2
python3 -c "from rknnlite.api import RKNNLite; print('ok')"
```

### 验收

- [ ] 同一张图，ONNX 与 RKNN 的框 IoU > 0.9、分数差 < 0.05
- [ ] 640×640 单帧推理 ≥ 30 FPS（3 核 NPU；yolov8n 应远超）
- [ ] 连续跑 10 分钟温度 < 80°C
- [ ] 量化后 mAP 掉点 < 3 个点（用 `tools/train_yolo.py` 的验证集复测）

---

## 三、阶段 2：板子 ↔ 飞控（先只读）

### 接线

- 飞控侧用 **TELEM2**（或任一空闲 UART），PX4 参数：
  - `MAV_1_CONFIG = TELEM2`
  - `MAV_1_MODE = Onboard`
  - `SER_TEL2_BAUD = 921600`（与脚本里的波特率一致）
- 板子侧：**TX/RX 交叉、共地、3.3V 电平**。
  Orange Pi 5 Pro 的 40pin 与 Orange Pi 5 **定义不同**，必须查官方 pinout 确认哪组 UART 默认启用。
- **接飞控前先做 UART 回环**：短接板子自己的 TX/RX，发一串字符能收回来，再接飞控。

### 系统侧

```bash
sudo usermod -aG dialout $USER          # 重新登录生效
sudo systemctl disable --now serial-getty@ttySX.service   # 释放串口控制台
```

### 先只读，不 arm

板子上先跑一个最小遥测脚本（等价于 `rc_monitor.py`），确认：

- [ ] 能连上，心跳稳定 10 分钟
- [ ] 高度 / 模式 / armed / 电量 / RC 状态都有数
- [ ] 拔掉飞控电源，脚本能发现断链（不是拿着旧值继续跑）
- [ ] 20Hz 控制循环不丢帧

> **待验证风险**：MAVSDK 的 aarch64 wheel 是否齐全。
> 先 `pip install mavsdk==3.15.3` 试；装不上就先用 `pymavlink` 做只读遥测把硬件链路验通，
> **不要**为了装依赖去改 `vnav/link.py` 的架构。

---

## 四、阶段 3：相机与标定

- **首选 USB UVC 摄像头**：免驱，`cv2.VideoCapture(0)` 直接通，`vnav/camera.py` 不用改。
- MIPI CSI 在 RK3588 上要走 rkisp / media-ctl，OpenCV 取流容易踩坑，第一版不折腾。
- 没有相机时，手机 IP Webcam（`http://<手机IP>:8080/video`）可以先验 `open_camera()` 和检测链路。
- **相机到货先标定**：张正友 → `calib.json`，这一步同时把课程第 4 周收尾。
  标定必须针对**最终装机的那颗镜头 + 最终分辨率**，换镜头/改分辨率要重标。

### 验收

- [ ] `calib.json` 重投影误差 < 0.5 px
- [ ] 2–5m 处单目测距误差 < 10%（和人高先验误差叠加后）
- [ ] 板子上 640×480 取流 ≥ 20 FPS，端到端延迟可接受（< 150ms）

---

## 五、阶段 4：代码接入（改动很小）

| 文件 | 改动 |
| --- | --- |
| `vnav/detectors.py` | 新增 `RknnDetector`，复用 `OnnxDetector._letterbox` / `_decode` / NMS |
| `vnav/config.py` | 加 `rknn_model_path`、`rknn_core_mask`；`detector` 支持 `"rknn"` |
| `vnav/camera.py` | 不改（USB 走 `LocalCamera`） |
| `run_tracking.py` | 不改 |
| `tools/` | 新增 `convert_rknn.py`、`bench_rknn.py` |

`RknnDetector` 的形状：

```python
class RknnDetector(OnnxDetector):
    def _load(self):
        from rknnlite.api import RKNNLite
        r = RKNNLite()
        r.load_rknn(self.cfg.rknn_model_path)
        r.init_runtime(core_mask=self.cfg.rknn_core_mask)
        self._session = r
        self._input_hw = (640, 640)
        return r
```

注意：`rknnlite` 的 `inference()` 返回 list，输出形状与 ONNX 一致时，`_decode` 可以直接复用。

---

## 六、阶段 5：上机顺序（安全门，不许跳）

1. 板子单独验完（阶段 0–1）
2. **拆桨**，板子接飞控，只读遥测
3. **拆桨**，地面 `run_tracking.py --no-arm`，看距离和状态机
4. 系留 / 低高度（≤1m）悬停，验证 20Hz setpoint 和 Offboard 进出
5. `docs/RC_OFFBOARD_SETUP.md` 清单第 5 项「Offboard 中打杆抢权」通过
6. 才允许真飞

红线不变：不拆桨不飞；`kill()` 不是收尾；异常必须收敛到悬停/降落；Offboard ≥2Hz。

---

## 七、风险清单（待验证）

| # | 风险 | 影响 | 应对 |
| --- | --- | --- | --- |
| 1 | `rknn-toolkit2` 在 WSL 24.04 装不上 | 转不了模型 | 用 Rockchip Docker 镜像 / conda py3.10 / 借一台 Ubuntu 22.04 |
| 2 | MAVSDK 无 aarch64 wheel | 板子上连不了飞控 | 先用 pymavlink 只读验证，再决定是否加链路后端 |
| 3 | 5 Pro 排针 UART 与 5 不同 | 接错口/没信号 | 查官方 pinout；先做 TX-RX 回环 |
| 4 | 供电掉压重启 | 空中失控 | 独立 5V/5A BEC、粗线、电容；地面满载复测 |
| 5 | 散热不足降频 | FPS 掉、延迟涨 | 散热片 + 风扇；监控温度 |
| 6 | 板子 2.4GHz WiFi 干扰遥控 | RC 丢链路 | 用 5GHz 或不开 WiFi；天线远离接收机 |
| 7 | USB 摄像头带宽/供电 | 掉帧、花屏 | 单摄像头、MJPEG、带供电 Hub 或独立 5V |
| 8 | 量化掉点 | 检测变差 | 扩量化集；不行就 FP16 |

---

## 八、记录表（参数改动必须填）

| 日期 | 参数 | 旧值 | 新值 | 依据 | 回退 |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |
