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

**状态：待采集。** 在这台 Mac 上跑下面的命令，把结果填回来：

```bash
sw_vers                      # macOS 版本
uname -m                     # arm64 = Apple Silicon / x86_64 = Intel
which -a python3 && python3 -V
python3 -m pip list 2>/dev/null | grep -Ei 'mavsdk|ultralytics|torch|opencv'
# 飞控插上 Mac 后：
ls /dev/tty.* /dev/cu.*      # 找 usbserial / usbmodem
```

| 项 | 值 |
| --- | --- |
| 角色 | 写文档、改代码、跑 PX4 SITL。**不接实物飞控飞行**（数传与供电以台式机为准） |
| 芯片 | Apple Silicon（M 系列），arm64 |
| 仿真栈 | PX4-Autopilot SITL + jMAVSim；MAVSDK 连 `udp://:14540` |
| Python | 待填（建议 3.10/3.11 独立 venv，别用系统 Python） |
| mavsdk | 待填（装 `mavsdk==3.15.3`，不要 3.17+） |
| torch | 待填（Apple Silicon 走 MPS 而非 CUDA；YOLO 比 4060 慢很多，仅做功能验证） |
| 数传端口 | 待填，形如 `serial:///dev/tty.usbmodem1101`（绝对路径是三个斜杠） |

### Mac 侧已知踩坑（来自 `devlogs/`，已验证）

- `empy` 必须降到 **3.3.4**，否则 PX4 编译报 `RAW_OPT` 冲突。
- `pyyaml` / `pyros-genmsg` 编译期依赖死锁，安装顺序有讲究。
- 完整步骤见 `devlogs/无人机项目开发日志.md`，别重复踩。

### Mac 上装依赖的建议

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "mavsdk==3.15.3"            # 只跑控制脚本时够用
pip install ultralytics                 # 需要跑视觉时再装，会自动带 torch
```

> Apple Silicon 上 `mavsdk` 的 gRPC 二进制有 arm64 wheel，一般能直接装；若报架构错误再考虑 Rosetta。

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
