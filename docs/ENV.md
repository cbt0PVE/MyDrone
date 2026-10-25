# 环境（按机器分）

> 本机路径、串口名、GPU 之类的信息只写这里，其他文档用中性说法。
> 换机器后先看对应小节；不确定就按下面命令重新采集一遍。

## A. Windows 台式机 · 实机调试

| 项 | 值 |
| --- | --- |
| 角色 | 连飞控、调参、跑飞行脚本、GPU 跑 YOLO |
| Python 环境 | conda `drone` · `C:\Users\10545\miniconda3\envs\drone\python.exe` |
| Python 版本 | 3.10.20 |
| mavsdk | 3.15.3（gRPC 版） |
| ultralytics | 8.4.60 |
| torch | 2.5.1+cu121，CUDA 可用（RTX 4060） |
| 数传端口 | `serial://COM5:57600`（COM 号随插拔变化，用设备管理器确认） |
| 工作目录 | `C:\Users\10545\Desktop\drone` |

**注意**：不要用 base 环境（Python 3.13 + mavsdk 3.17.4，那个包已更名 `mavsdk-grpc`，会告警且 API 不兼容）。

## B. macOS 笔记本 · 写文档 / 改代码

**状态：已采集（2026-10-25，Mac 本机实测）。** 需要重查时跑：

```bash
sw_vers && uname -m
which -a python3 && python3 -V && /opt/homebrew/bin/python3 -V
python3 -m pip list 2>/dev/null | grep -Ei 'mavsdk|ultralytics|torch|opencv'
ls /dev/tty.* /dev/cu.*      # 飞控/数传插上后找 usbserial / usbmodem
```

| 项 | 值 |
| --- | --- |
| 角色 | 写文档、改代码、跑 PX4 SITL。**不接实物飞控飞行**（数传与供电以台式机为准） |
| 系统 | macOS 27.0.1（build 26A434），`uname -r` = 27.0.0 |
| 芯片 | Apple Silicon，arm64（`uname -m` / `arch` 均为 arm64） |
| Homebrew | 7.0.9，前缀 `/opt/homebrew` |
| Python（PATH 默认） | `/usr/bin/python3` = **3.9.6**（系统自带，先于 brew 命中） |
| Python（brew） | `python@3.14` = 3.14.5（PATH 中排在系统 Python 之后，直接敲 `python3` 用的是 3.9.6） |
| 依赖安装位置 | 用户级 site-packages `~/Library/Python/3.9/lib/python/site-packages`，**不是 venv**；仓库内没有 `.venv/` |
| mavsdk | 3.15.3（`import mavsdk` 可用，arm64）— 已验证 |
| torch | 2.8.0；`torch.backends.mps.is_available() == True`（走 MPS，不是 CUDA）— 已验证 |
| ultralytics | 8.4.53（torchvision 0.23.0，opencv-python 4.13.0.92，numpy 2.0.2）— 已安装，未在本机跑过推理 |
| PX4 编译依赖 | empy 3.3.4、pyros-genmsg 0.5.8、PyYAML 6.0.3、kconfiglib 14.1.0、jsonschema 4.25.1、future 0.18.2（同在 3.9 用户 site-packages）— 已验证，与踩坑记录一致 |
| PX4-Autopilot 检出位置 | `~/Developer/DroneProject/PX4-Autopilot`（在仓库外，不入库） |
| PX4 版本 | 分支 main，HEAD `96afb47`（2026-05-11），**shallow clone、无 tag，版本号未确认** |
| SITL 产物 | `build/px4_sitl_default/bin/px4` 存在（2026-05-21 构建）；本次未重新启动验证 |
| 仿真器 | jMAVSim **未构建**（`Tools/jMAVSim/out` 不存在） |
| Java | 仅 OpenJDK **25.0.3**（Temurin）；PX4 `Tools/setup/macos.sh` 要求 `openjdk@17`，未安装 → 待验证（25 很可能编不过 jMAVSim） |
| QGroundControl | **未安装**（/Applications 与 ~/Applications 都没有）→ 本机做不了 RC 通道映射 |
| 数传端口 | **未接入飞控**（无 `/dev/tty.usbmodem*` / `usbserial*`）。本机不接实物飞控飞行；真要插，地址形如 `serial:///dev/tty.usbmodem1101`（绝对路径三个斜杠） |
| 视觉测试素材 | `yolov8n.pt` / `drone_test.mp4` 均不在本机（`.gitignore` 已排除，按需自备） |

### Mac 侧已知踩坑（来自 `devlogs/`，已验证）

- `empy` 必须降到 **3.3.4**，否则 PX4 编译报 `RAW_OPT` 冲突。
- `pyyaml` / `pyros-genmsg` 编译期依赖死锁，安装顺序有讲究。
- 完整步骤见 `devlogs/无人机项目开发日志.md`，别重复踩。

### Mac 上装依赖的建议

**现状（2026-10-25）**：所有依赖直接装在系统 Python 3.9.6 的用户 site-packages 里，能跑但不隔离；`brew python@3.14` 也在 PATH 里，直接 `python3 -m venv` 会拿 3.9、`python3.14 -m venv` 会拿 3.14，两者别混。PX4 的编译脚本当前就是走 3.9.6 这套（`empy 3.3.4` 装在这里），**动 Python 前先确认 SITL 还能编**。

若要新建隔离环境（建议 3.11，PX4 与 mavsdk 都稳）：

```bash
brew install python@3.11
/opt/homebrew/bin/python3.11 -m venv .venv && source .venv/bin/activate
pip install "mavsdk==3.15.3"            # 只跑控制脚本时够用
pip install ultralytics                 # 需要跑视觉时再装，会自动带 torch（MPS）
```

> Apple Silicon 上 `mavsdk` 的 gRPC 二进制有 arm64 wheel，已验证可直接装；报架构错误再考虑 Rosetta。

### Mac 侧待办（采集时发现，未处理）

1. **jMAVSim 跑不起来**：只装了 JDK 25，PX4 要求 `openjdk@17`；`make px4_sitl jmavsim` 大概率在编 jMAVSim 时报 `release version`/`class file` 错误。要跑 SITL 仿真就先 `brew install openjdk@17` 并让 `JAVA_HOME` 指向它（待验证）。
2. **PX4 是 shallow clone（depth 1，无 tag）**：查不到固件版本号，而 `COM_RC_OVERRIDE` 是否位掩码**取决于 PX4 版本**。需要用 `ver all` 或在 QGC 里读固件版本，别靠猜。
3. **QGC 未装**：RC 通道映射（`RC_MAP_OFFB_SW` 的前置）在 Mac 上做不了，仍等 Windows 侧出表。
4. 系统 Python 3.9 已被 PX4 上游弃用、homebrew 侧是 3.14；这套组合能编是运气，换 PX4 版本或重装依赖时优先考虑 3.11 venv。

## 环境变量

| 变量 | 用途 | 缺省 |
| --- | --- | --- |
| `DRONE_PORT` | MAVSDK 连接地址 | 见上表各平台 |

用法（PowerShell）：`$env:DRONE_PORT="serial://COM6:57600"`
用法（zsh）：`export DRONE_PORT="serial:///dev/tty.usbmodem1101"`

## 大文件

`yolov8n.pt`、`drone_test.mp4` 不进 git（`.gitignore` 已排除）。
- Mac 上需要视觉测试时：从 Windows 拷过来，或直接 `yolo` 首次运行时自动下载权重。
- 真要同步大文件，别塞 git，用网盘/移动硬盘。
