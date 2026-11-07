# RKNN 上板：ONNX → RKNN → 板上推理

> 目标：把 `best.onnx`（YOLOv8n 单类 person）转成 `best.rknn`，在香橙派 5 Pro 的
> 3 核 NPU 上跑起来，并保持和 ONNX 路径同一套前/后处理。
>
> 原则：**转换只在 x86_64 Linux / WSL 上做；板子只装 `rknn-toolkit-lite2`。**

---

## 一、版本配对（重要）

| 组件 | 版本 | 位置 |
| --- | --- | --- |
| 板子 NPU 驱动 | **0.9.6** | 内核 `rknpu`，`/sys/kernel/debug/rknpu/version` |
| 板子系统运行时 | **1.4.0（2022-09）** | `/usr/lib/librknnrt.so`（**偏旧**） |
| 转换工具 | **rknn-toolkit2 2.3.2** | WSL / x86_64，Python 3.10 |
| 板上推理 | **rknn-toolkit-lite2 2.3.2** | 香橙派，Python 3.10，aarch64 |

> 板子镜像自带 `librknnrt 1.4.0`，和 2.3.2 的模型不一定匹配。
> `rknn-toolkit-lite2` 的 wheel 通常自带一份匹配的 `librknnrt.so`；
> 如果报 “model version not match / driver version” 再处理（见第六节）。
> **不要一上来就替换系统库**，先备份、先试 wheel 自带的那份。

为什么不用 2.5.0：它更新，可能要求更高版本的 NPU 驱动；板子是 2024 年的
0.9.6，先用 2.3.2 这代更稳。

---

## 二、WSL 转换环境（x86_64）

```bash
# 一次性：Python 3.10 + rknn-toolkit2
bash tools/setup_rknn_wsl.sh

# 之后每次转换：
source ~/miniconda3/etc/profile.d/conda.sh
conda activate rknn
```

生成量化图片列表（100–200 张有人的图）：

```bash
python tools/make_rknn_dataset.py \
    --images /mnt/c/Users/<你>/Desktop/drone/datasets/coco_person/images/train \
    --limit 100 \
    --output /tmp/rknn_dataset.txt
```

转换：

```bash
python tools/convert_rknn.py \
    --onnx /mnt/c/Users/<你>/Desktop/drone/runs/detect/runs/detect/coco_person/weights/best.onnx \
    --dataset /tmp/rknn_dataset.txt \
    --output /mnt/c/Users/<你>/Desktop/drone/runs/detect/runs/detect/coco_person/weights/best.rknn
```

- `--no-quant` 出 FP16，用于对照“是不是量化掉点”。
- 输入归一化：`mean=0, std=255`，对应 ultralytics ONNX 的 RGB 0–1 输入。
- 当前 ONNX：opset **19**，输入 `1x3x640x640`，输出 `1x5x8400`。
  如果 2.3.2 不认 opset 19，用 ultralytics 重新导出 `opset=12`。

---

## 三、板子安装（aarch64）

板子镜像默认**没有 pip、numpy、cv2**，用用户级安装，不需要 sudo：

```bash
# 1. 装 pip（用户级）
curl -sS -L https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user
export PATH="$HOME/.local/bin:$PATH"

# 2. 依赖
python3 -m pip install --user "numpy==1.26.4" psutil ruamel.yaml

# 3. RKNN Lite2（aarch64 cp310 轮子）
python3 -m pip install --user --no-deps "rknn-toolkit-lite2==2.3.2"
```

验证：

```bash
python3 -c "from rknnlite.api import RKNNLite; print('ok')"
```

> 也可以用仓库里的 `tools/setup_rknn_board.sh` 一次性做（脚本含 pip bootstrap）。

---

## 四、板上跑基准

把 `best.rknn` 和 `tools/bench_rknn.py` 拷到板子：

```powershell
scp runs\detect\runs\detect\coco_person\weights\best.rknn orangepi:~/
scp tools\bench_rknn.py orangepi:~/
```

板上：

```bash
python3 ~/bench_rknn.py --model ~/best.rknn --runs 50
```

输出：

- 输入/输出形状
- 单帧平均/最小/最大耗时
- FPS
- 输出是否 NaN/Inf

验收目标：**640×640、3 核 NPU、≥30 FPS**（yolov8n 单类应远超）。

---

## 五、代码接入

| 文件 | 改动 |
| --- | --- |
| `vnav/detectors.py` | 新增 `RknnDetector`，复用 `OnnxDetector` 的 letterbox/decode/NMS；`build_detector` 识别 `.rknn` |
| `vnav/config.py` | 新增 `rknn_model_path` / `rknn_core_mask` / `rknn_input_size` |
| `tools/convert_rknn.py` | ONNX → RKNN 转换 |
| `tools/make_rknn_dataset.py` | 生成量化图片列表 |
| `tools/bench_rknn.py` | 板上 FPS/耗时基准 |

用法：

```bash
# 板上，直接用 .rknn
python3 run_tracking.py --weights ~/best.rknn --no-arm

# 或者在 config.py 里设 detector="rknn"
```

`RknnDetector` 是懒加载的：没装 `rknnlite` 也能 import / 构造，只有真正推理时才报错。

---

## 六、常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `load_rknn` 失败 | 模型/运行时版本不匹配 | 用同版本 toolkit2/lite2；或换 wheel 自带的 `librknnrt.so` |
| `init_runtime` 失败 | `librknnrt.so` 或 NPU 驱动不匹配 | 先备份 `/usr/lib/librknnrt.so`，再试匹配版本；不要盲删 |
| 输出形状不对 | RKNN 输入布局/输出顺序 | 确认 NCHW；`bench_rknn.py` 会打印形状 |
| 精度掉很多 | INT8 量化集不代表飞行画面 | 扩到 200 张；或先 FP16 对照 |
| `import cv2` 失败 | 板子没装 OpenCV | 用户级 `opencv-python-headless`，或 apt（需 sudo） |
| 速度慢 | 只用了单核 / 降频 | `rknn_core_mask=NPU_CORE_0_1_2`；看温度是否 >80°C |

---

## 七、当前状态

- [x] 板子开机、NPU 驱动 v0.9.6、SSH 免密
- [x] 代码侧 `RknnDetector` / 转换脚本 / 基准脚本
- [ ] WSL Python 3.10 + rknn-toolkit2 2.3.2 安装（下载中，网络较慢）
- [ ] 转出 `best.rknn`
- [ ] 板子 lite2 安装 + 基准
- [ ] 精度对照（ONNX vs RKNN）

> 网络是当前的主要瓶颈：板子 WiFi 和 WSL 下载都不快。装完一次就固定下来，
> 后面不再反复下载。
