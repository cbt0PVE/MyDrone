# 香橙派 5 Pro 构建日志（开箱 → SSH → RKNN）

> 用途：把“每一步做了什么、装了什么版本、结果如何”按顺序记下来。
> 说明：**这份是事后补的**，部分时间点为近似；命令和版本以实际产物为准。
> 结论性文档见 `docs/STATUS.md`、`docs/RKNN.md`；本文是过程流水账。

---

## 0. 最终状态（先看结论）

| 项 | 结果 |
| --- | --- |
| 板子 | Orange Pi 5 Pro，16GB，Ubuntu 22.04（Orange Pi 1.0.6 Jammy） |
| 内核 / NPU 驱动 | 5.10.160-rockchip-rk3588 / RKNPU **0.9.6** |
| 访问方式 | WiFi `192.168.100.151`，Windows 上 `ssh orangepi` 免密 |
| 推理栈 | rknn-toolkit-lite2 **2.3.2** + librknnrt **2.3.2**（用户态挂载） |
| 模型 | **3 头 INT8** `best_heads.rknn`（4.13MB） |
| 精度 | 同图 ONNX vs RKNN top 框 **IoU 0.9916**，score 0.808 vs 0.831 |
| 速度 | 推理 **18.3 FPS**；端到端（含 DFL/NMS/测距）**13.7 FPS** |

---

## 1. 板子开箱与系统（较早完成，简述）

| 步骤 | 操作 | 结果 |
| --- | --- | --- |
| 1 | 确认 SD 卡（32GB，F:，内含 H2testw 测试文件） | 卡是真的 32GB，测试文件无价值 |
| 2 | 下载 `Orangepi5pro_1.0.6_ubuntu_jammy_desktop_xfce_linux5.10.160.img` | 1.55GB 7z → 8.25GB img，SHA256 校验通过 |
| 3 | 写入 SD 卡（先失败一次：Windows 自动挂载新分区导致 30% 掉线） | 关闭 automount 后重写，回读 SHA256 通过 |
| 4 | 首次开机 | 进桌面；Ubuntu 22.04 / 内核 5.10.160 / NPU 0.9.6 / 16GB |
| 5 | 配置 SSH 免密 | Windows 密钥 + `~/.ssh/config` 别名 `orangepi` |
| 6 | 配置 WiFi `helta的新路由` | `wlan0` 拿到 `192.168.100.151`，开机自动连 |
| 7 | 无线/有线切换 | `ssh orangepi`（WiFi）/ `ssh orangepi-lan`（有线） |
| 8 | `Prompt=never` | 禁止误升 Ubuntu 24.04（BSP 配套 5.10 + NPU 0.9.6） |

> 板子初始 Python 3.10.12，**没有 pip、numpy、cv2**；系统自带
> `/usr/lib/librknnrt.so` 是 **1.4.0（2022-09）**。

---

## 2. RKNN 环境安装（按实际顺序）

### 2.1 板子侧（aarch64）

| 步骤 | 命令/操作 | 结果 |
| --- | --- | --- |
| 1 | 下载 `get-pip.py`，`python3 get-pip.py --user` | pip **26.3** 装到 `~/.local` |
| 2 | `pip install --user numpy==1.26.4 psutil ruamel.yaml` | numpy 1.26.4；psutil 系统已有；ruamel.yaml 0.19.1 |
| 3 | `pip install --user --no-deps rknn-toolkit-lite2==2.3.2` | lite2 2.3.2（aarch64 cp310） |
| 4 | `pip install --user opencv-python-headless` | **踩坑**：装了 5.0.0.93，把 numpy 升到 2.2.6 |
| 5 | 降级 `numpy==1.26.4` + `opencv-python-headless==4.10.0.84` | numpy 1.26.4 / cv2 4.10.0，稳定 |
| 6 | 从 GitHub tag `v2.3.2` 下载 `librknnrt.so` | 放到 `~/.local/lib/rknn/librknnrt.so`，版本 2.3.2 |
| 7 | `pip install --user onnxruntime` | 1.23.2（作为 CPU 兜底，6.9 FPS） |

板子最终版本：

```text
Python 3.10.12
pip 26.3
numpy 1.26.4
opencv-python-headless 4.10.0.84
rknn-toolkit-lite2 2.3.2
librknnrt 2.3.2（~/.local/lib/rknn，不覆盖系统）
onnxruntime 1.23.2
```

### 2.2 WSL 侧（x86_64 转换）

| 步骤 | 命令/操作 | 结果 |
| --- | --- | --- |
| 1 | 检查 WSL：Ubuntu 24.04 / Python 3.12 | 官方 rknn-toolkit2 2.3.2 只有 cp310/cp311 x86 轮子 |
| 2 | 下载 Miniconda（先官方源，~200KB/s；改清华镜像） | 210MB，清华 ~50MB/s |
| 3 | `conda create -y -n rknn python=3.10` | 先报 ToS 未接受；`conda tos accept ...` 后成功 |
| 4 | `pip install --no-deps rknn-toolkit2==2.3.2` | 39.6MB 轮子 |
| 5 | 装依赖：numpy 1.26.4、onnx、onnxruntime、opencv-python-headless、protobuf、scipy、tqdm、fast-histogram | 成功 |
| 6 | 缺 torch → 先 pip 官方 CPU 轮子 | 195MB 只有 ~90KB/s，下到 58MB 放弃 |
| 7 | 改 `conda install -c 清华 pytorch=2.4.0 cpuonly` | 269MB，成功；torch 2.4.0 |
| 8 | `import torch` 报 `iJIT_NotifyEvent` | MKL 2025 与 torch 2.4 不兼容 |
| 9 | `conda install mkl=2023.1.0 intel-openmp=2023.1.0`（清华 pkgs/main） | torch 2.4.0 可 import |
| 10 | `from rknn.api import RKNN` 报 `pkg_resources` | `pip install 'setuptools<81'` → 80.10.2 |
| 11 | `load_onnx` 报 `onnx has no attribute mapping` | `pip install onnx==1.16.1` |

WSL 最终关键版本：

```text
Python 3.10.22（conda env rknn）
rknn-toolkit2 2.3.2
torch 2.4.0（conda py3.10_cpu_0）
mkl 2023.1.0 / intel-openmp 2023.1.0
onnx 1.16.1
onnxruntime 1.23.2
opencv-python-headless 4.11.0.86
numpy 1.26.4
setuptools 80.10.2
```

### 2.3 板上 MAVSDK 预检（2026-11-07）

| 步骤 | 命令/操作 | 结果 |
| --- | --- | --- |
| 1 | `pip install --user mavsdk==3.15.3` | 18.2MB aarch64 轮子，grpcio 1.85.1 也是 aarch64 |
| 2 | `from mavsdk import System` | OK |
| 3 | `import vnav.link` | OK |
| 4 | 检查 `mavsdk_server` | 存在且可执行 |

> 结论：板上 MAVSDK 不是风险；下一步接 UART 只差硬件和串口配置。

---

### 2.4 板上视频链路（2026-11-07）

| 步骤 | 操作 | 结果 |
| --- | --- | --- |
| 1 | 用 COCO 行人图合成 120 帧横向移动视频 | `person_pan.avi`，640×480，8.4MB |
| 2 | 板上 `open_camera → RknnDetector → 标注 → 写 AVI` | 120 帧 / 93 检出 / **11.2 FPS** |
| 3 | 输出抽帧检查 | 框落在人身上，conf 0.84–0.88；后半段人走出画面 |

> 93/120 不是检测崩：合成视频的裁剪窗口后半段把人物移出画面。
> 工具：`tools/video_pipeline.py`。

### 2.5 MOT 与遮挡基准（2026-11-07）

| 场景 | 结果 |
| --- | --- |
| 视频无 MOT | 93/120 帧有目标 |
| 视频 MOT 安全模式 | 68/120（丢失帧不返回预测框） |
| 视频 MOT 预测演示 | 119/120（只用于演示） |
| 遮挡 0.5s，`max_age=15` | 保持 id=1 |
| 遮挡 1s / 2s，`max_age=15` | 换 id=2 |
| 遮挡 0.5/1/2s，`max_age=45` | **全部保持 id=1，重捕获 0 帧** |

工具：`tools/video_pipeline.py --mot`、`tools/occlusion_bench.py`。

### 2.6 控制仿真（2026-11-07）

| 控制 | 稳态误差（0.5m/s 目标，保持 2.5m） |
| --- | --- |
| P-only | 0.624m |
| PI（ki=0.3，限幅 2.0，关接近降速） | **0.056m** |

工具：`tools/control_sim.py`；参数变更见 `docs/TRACKING_ALGO_PLAN.md`。

---

## 3. 转换尝试（按顺序，含失败）
量化集：`datasets/coco_person/images/train` 前 100 张。

| # | 模型 | 结果 |
| --- | --- | --- |
| 1 | 全模型 INT8，normal | 4.56MB；板上加载后**类别通道全 0** |
| 2 | 全模型 FP16（`--no-quant`） | 7.90MB；0–1 输入 score 0.003，**乘 255 后 score 0.808**；4.8 FPS |
| 3 | 全模型 INT8 + `quant_img_RGB2BGR=True` | 4.78MB；类别仍全 0 |
| 4 | 全模型 INT8 + `optimization_level=0` | 4.78MB；类别仍全 0 |
| 5 | 全模型 INT8 + `quantized_hybrid_level=1` | 4.80MB；类别仍全 0 |
| 6 | `quantized_dtype='w8a16'` | **rk3588 不支持** |
| 7 | `quantized_algorithm='mmse'` | 2 分钟才 1/119，**太慢，放弃** |
| 8 | **3 头 INT8（`--heads`）** | 4.13MB；6 输出；类别 logits 正常，**成功** |

3 头输出顺序：

```text
(1,64,80,80) (1,1,80,80)
(1,64,40,40) (1,1,40,40)
(1,64,20,20) (1,1,20,20)
```

---

## 4. 板上运行时问题

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| `Invalid RKNN model version 6` | 加载的是系统 1.4.0 | 需要 2.3.2 运行时 |
| `LD_PRELOAD` / `LD_LIBRARY_PATH` 无效 | `rknnlite` 写死 `/usr/lib/librknnrt.so` | `unshare -r -m` + bind mount |
| 绑定后仍报 1.4.0 | 环境变量没覆盖绝对路径 | 用 `tools/run_with_rknn.sh` 包裹整个进程 |

`tools/run_with_rknn.sh` 的核心：

```bash
unshare -r -m bash -c '
  mount --bind "$HOME/.local/lib/rknn/librknnrt.so" /usr/lib/librknnrt.so
  exec "$@"
' "$@"
```

---

## 5. 代码改动

| 文件 | 改动 |
| --- | --- |
| `vnav/detectors.py` | `RknnDetector`；`_infer`：0–255 + NHWC；`_postprocess`：6 输出走 3 头；`_decode_heads`：DFL softmax + sigmoid；`_finish`：复用 NMS/测距；修 `_letterbox` 前未 `_load()` 的 bug |
| `vnav/config.py` | `rknn_model_path` / `rknn_core_mask` / `rknn_input_size` / `rknn_input_scale=255` |
| `tools/convert_rknn.py` | `--heads` / `--quant-algorithm` / `--quant-dtype` / `--rgb2bgr` / `--opt-level` / `--hybrid-level` |
| `tools/make_rknn_dataset.py` | 生成 100 张量化列表 |
| `tools/bench_rknn.py` | 板上 FPS 基准（默认 NHWC） |
| `tools/eval_rknn_batch.py` | 批量 ONNX↔RKNN 框对照 |
| `tools/occlusion_bench.py` | 遮挡 N 帧的 ID 保持/重捕获基准 |
| `tools/control_sim.py` | 二维控制仿真（P vs PI） |
| `tools/enroll_server.py` | 起飞前手机/PC 网页点选目标，保存 target.json |
| `tools/run_with_rknn.sh` | 用户态加载 2.3.2 运行时 |
| `tools/setup_rknn_wsl.sh` | WSL 环境脚本（onnx 1.16.1 / setuptools<81） |
| `tools/setup_rknn_board.sh` | 板子用户级安装（OpenCV 4.10 固定） |
| `tests/test_vision_smoke.py` | 加 `test_rknn_detector_selection` / `test_rknn_heads_decode`（9/9） |
| `vnav/tracker.py` | **新增**：EMA + 跳变抑制的目标时序滤波 |
| `vnav/mot.py` | **新增**：IoU + 外观关联、目标锁定（`--mot`） |
| `vnav/appearance.py` | **新增**：HSV 直方图 / 相似度（ReID-lite） |
| `vnav/detectors.py` | `detect_all()`；`build_detector` 可按 `use_mot` 包一层 |
| `vnav/tracking.py` | 控制走滤波值；PI 距离环；安全看门狗仍用原始检测 |
| `tests/test_target_filter.py` | 4 项滤波回归测试 |
| `tests/test_mot.py` | 8 项 MOT/锁定/外观回归测试 |
| `tests/test_appearance.py` | 2 项外观相似度测试 |

---

## 6. 验收结果

| 指标 | 值 |
| --- | --- |
| 3 头 INT8 检出 | conf **0.831**，中心 `(292, 355)` |
| ONNX 同图 top 框 | `[160.5, 117.2, 440.7, 595.0]`，score 0.808 |
| RKNN 同图 top 框 | `[161.6, 116.9, 440.8, 593.2]`，score 0.831 |
| **IoU** | **0.9916** |
| 批量 40 张最佳匹配 IoU | **0.9899**（min 0.9757） |
| 批量 top-1 IoU | 0.9128（多人图选人不同） |
| 批量分数差 | 均值 0.0123 / 最大 0.0749 |
| 批量检出（0.35） | ONNX 40/40，RKNN 40/40，漏检 0 |
| 推理（NHWC） | 54.5 ms / **18.3 FPS** |
| 端到端 | 72.9 ms / **13.7 FPS** |
| 冒烟测试 | **9/9** |
| yaw 回归 | 2/2 |
| 日志回归 | 2/2 |

---

## 7. 提交记录

| commit | 内容 |
| --- | --- |
| `0366f72` | 香橙派上板、飞行日志、失控保护复盘（大提交） |
| `c7c840a` | 记录 torch/MKL 卡点与恢复命令 |
| `fc19f16` | 3 头 INT8 上板，推理 18.3 / 端到端 13.7 |
| `ad1dfda` | 3 头精度对照 IoU 0.9916 |

---

## 8. 没做/没记的

- 每一步的**精确时间戳**没有逐个记录，本文按操作顺序补。
- 部分失败命令的完整报错只留在对话里，没有单独存日志。
- 板上系统包（apt）只装了 `python3-pip` 相关？实际 pip 是 `get-pip.py` 用户级；
  `onnxruntime` 是后期兜底，不是最终路径。
- `best_mmse.rknn` 被中断，未产出可用模型。
- 30 FPS 优化、相机标定、实机飞行还没做。

---

## 9. 复现入口

```bash
# 板子（用户级）
bash tools/setup_rknn_board.sh
bash tools/run_with_rknn.sh python3 ~/bench_rknn.py --model ~/best_heads.rknn --format nhwc --runs 50

# WSL（一次性）
bash tools/setup_rknn_wsl.sh
python tools/make_rknn_dataset.py --images datasets/coco_person/images/train --limit 100 --output /tmp/rknn_dataset.txt
python tools/convert_rknn.py --onnx .../best.onnx --dataset /tmp/rknn_dataset.txt --output .../best_heads.rknn --heads
```

> 注意：`setup_rknn_wsl.sh` 只覆盖基础依赖；ONNX 1.16.1、setuptools<81、
> MKL 2023.1 这三个坑见 `docs/RKNN.md` 第二节。
