# RKNN 上板：ONNX → RKNN → 板上推理

> 目标：把 `best.onnx`（YOLOv8n 单类 person）转成 `best.rknn`，在香橙派 5 Pro 的
> 3 核 NPU 上跑起来，并保持和 ONNX 路径同一套前/后处理。
>
> 原则：**转换只在 x86_64 Linux / WSL 上做；板子只装 `rknn-toolkit-lite2`。**

---

## 一、先记住这个坑：全模型 INT8 不能直接用

YOLOv8 导出的完整 ONNX 输出是 `(1, 5, 8400)`（4 个框参数 + 1 个类别分数）。
在 **RKNN Toolkit2 2.3.2 + rk3588** 上，INT8 量化后：

- 前 4 个通道（框）正常；
- **第 5 个通道（类别分数）整列为 0**，sigmoid 后全是 0。

试过 `mmse` / `kl_divergence` / `rgb2bgr` / `optimization_level=0` /
`quantized_hybrid_level=1` / 换输入 dtype，**都没救回来**；FP16 正常但只有 4.8 FPS。

**正确解法：把模型切在 3 个检测头，DFL/分类后处理放 Python。**
转换时用 `--heads`，得到 6 个输出：

```text
(1,64,80,80) (1,1,80,80)   stride 8
(1,64,40,40) (1,1,40,40)   stride 16
(1,64,20,20) (1,1,20,20)   stride 32
```

`RknnDetector._decode_heads()` 负责 DFL softmax + sigmoid，再复用 NMS/测距。

---

## 二、版本配对（已实测）

| 组件 | 版本 | 位置 |
| --- | --- | --- |
| 板子 NPU 驱动 | **0.9.6** | 内核 `rknpu` |
| 板子系统运行时 | 1.4.0（镜像自带，**太旧**） | `/usr/lib/librknnrt.so` |
| 板子实际运行时 | **2.3.2**（放用户目录） | `~/.local/lib/rknn/librknnrt.so` |
| 转换工具 | **rknn-toolkit2 2.3.2** | WSL / x86_64，Python 3.10 |
| 板上推理 | **rknn-toolkit-lite2 2.3.2** | 香橙派，Python 3.10，aarch64 |

### 转换环境的三个隐藏依赖

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `module 'onnx' has no attribute 'mapping'` | ONNX ≥1.17 删了 `onnx.mapping` | `pip install onnx==1.16.1` |
| `No module named 'pkg_resources'` | setuptools ≥81 移除了 | `pip install 'setuptools<81'` |
| `undefined symbol: iJIT_NotifyEvent` | conda torch 2.4 + MKL 2025 不兼容 | `conda install mkl=2023.1.0 intel-openmp=2023.1.0` |

> 这三个都踩过，装一次就固定下来。`tools/setup_rknn_wsl.sh` 已包含基本依赖，
> 但 MKL 降级和 ONNX 1.16.1 可能需要手动补，见第六节。

---

## 三、WSL 转换

```bash
# 一次性环境（Miniconda + py3.10 + rknn-toolkit2 2.3.2）
bash tools/setup_rknn_wsl.sh

# 生成量化图片列表（100–200 张有人的图）
python tools/make_rknn_dataset.py \
    --images /mnt/c/Users/<你>/Desktop/drone/datasets/coco_person/images/train \
    --limit 100 \
    --output /tmp/rknn_dataset.txt

# 3 头转换（推荐）
python tools/convert_rknn.py \
    --onnx /mnt/c/Users/<你>/Desktop/drone/runs/detect/runs/detect/coco_person/weights/best.onnx \
    --dataset /tmp/rknn_dataset.txt \
    --output /mnt/c/Users/<你>/Desktop/drone/runs/detect/runs/detect/coco_person/weights/best_heads.rknn \
    --heads
```

- `--heads` 输出 6 个张量；不加就是全模型 `(1,5,8400)`（INT8 会坏，不推荐）。
- `--no-quant` 出 FP16，用于对照，但板上只有 4.8 FPS，不实用。
- 输入归一化：转换时 `std=255`，所以**板上要喂 0–255**，不是 0–1。
- 当前 ONNX opset 19，2.3.2 可以读；如果以后报 opset 不支持，重新导出 opset 12。

---

## 四、板子安装

板子镜像默认**没有 pip、numpy、cv2**，全部用户级安装，不需要 sudo：

```bash
# 1. pip
curl -sS -L https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user
export PATH="$HOME/.local/bin:$PATH"

# 2. 依赖（OpenCV 4.10 兼容 numpy 1.x）
python3 -m pip install --user "numpy==1.26.4" psutil ruamel.yaml
python3 -m pip install --user "opencv-python-headless==4.10.0.84"

# 3. RKNN Lite2
python3 -m pip install --user --no-deps "rknn-toolkit-lite2==2.3.2"
```

也可以用 `tools/setup_rknn_board.sh` 一次做完。

### 运行时 2.3.2（关键）

镜像自带的 `/usr/lib/librknnrt.so` 是 1.4.0，加载 2.3.2 模型会报：

```text
Invalid RKNN model version 6
```

但 `rknnlite` 里写死了 `/usr/lib/librknnrt.so`，`LD_LIBRARY_PATH`/`LD_PRELOAD`
都覆盖不了。当前用**用户态 mount namespace** 临时替换，不需要 sudo：

```bash
bash tools/run_with_rknn.sh python3 your_script.py
```

它内部执行：

```bash
unshare -r -m bash -c 'mount --bind ~/.local/lib/rknn/librknnrt.so /usr/lib/librknnrt.so; exec "$@"'
```

- 需要内核启用 unprivileged user namespace；本板实测可用。
- 不会修改系统库，退出即恢复。
- 如果以后拿到 sudo，最干净的做法是备份系统库后直接替换。

---

## 五、实测结果（2026-11-07）

测试图：`datasets/coco_person/images/train/000000000872.jpg`（有人）。
板上用 `RknnDetector`（3 头 + DFL + NMS + 测距）：

| 指标 | 结果 |
| --- | --- |
| 输出 | 6 个张量，形状符合预期 |
| 检出 | **conf 0.831**，框中心 `(292, 355)` |
| ONNX 同图 top 框 | `[160.5, 117.2, 440.7, 595.0]`，score 0.808 |
| RKNN 同图 top 框 | `[161.6, 116.9, 440.8, 593.2]`，score 0.831 |
| 框 IoU（ONNX vs RKNN） | **0.9916** |
| 单帧推理（NHWC） | 54.5 ms / **18.3 FPS** |
| 端到端（含 letterbox + DFL + NMS + 测距） | 72.9 ms / **13.7 FPS** |
| FP16 全模型 | 209 ms / 4.8 FPS（不可用） |
| ONNX Runtime CPU | 144 ms / 6.9 FPS（精度对，速度不够） |
| 全模型 INT8 | 类别通道全 0（不可用） |

> 13.7 FPS 对 2.5m 慢速跟随够用（控制 20Hz，目标年龄 ~73ms），
> 但离 30 FPS 还有距离。下一步优化点在 DFL/NMS 的 Python 后处理（约 19ms）
> 和输入转换；要冲 30 FPS 需要更彻底的后处理/C++ 或更小输入尺寸。

---

## 六、怎么用

板上：

```bash
# 纯视觉（不连飞控）
bash ~/run_with_rknn.sh python3 ~/run_tracking.py --weights ~/best_heads.rknn --no-arm --no-window

# 基准
bash ~/run_with_rknn.sh python3 ~/bench_rknn.py --model ~/best_heads.rknn --format nhwc --runs 50
```

`RknnDetector` 也可以被 `run_tracking.py` 直接使用：`--weights xxx.rknn` 即走 RKNN。

代码侧：

| 文件 | 作用 |
| --- | --- |
| `vnav/detectors.py` | `RknnDetector`：3 头 DFL/sigmoid + 复用 NMS/测距 |
| `vnav/config.py` | `rknn_model_path` / `rknn_core_mask` / `rknn_input_size` / `rknn_input_scale` |
| `tools/convert_rknn.py` | `--heads` / 量化 / 输出 |
| `tools/make_rknn_dataset.py` | 量化图片列表 |
| `tools/bench_rknn.py` | 板上 FPS/耗时 |
| `tools/run_with_rknn.sh` | 用户态绑定 2.3.2 运行时 |

---

## 七、排错顺序

1. **`Invalid RKNN model version 6`** → 没用 `run_with_rknn.sh`，板子还在用 1.4.0。
2. **`module 'onnx' has no attribute 'mapping'`** → ONNX 降到 1.16.1。
3. **`No module named 'pkg_resources'`** → setuptools <81。
4. **`iJIT_NotifyEvent`** → MKL 2023.1 / intel-openmp 2023.1。
5. **检不出人 / 分数全 0** → 用了全模型 INT8；换 `--heads`。
6. **分数 0.00x** → 输入没乘 255；`rknn_input_scale=255`。
7. **速度只有 14 FPS** → 输入用 NHWC；后处理是主要开销，别指望零成本。

---

## 八、当前状态

- [x] 板子开机、NPU 驱动 0.9.6、SSH 免密
- [x] 板子 pip / numpy 1.26.4 / OpenCV 4.10 / lite2 2.3.2
- [x] 板子运行时 2.3.2（用户目录 + 用户态 bind mount）
- [x] WSL py3.10 + toolkit2 2.3.2 + 依赖修复
- [x] **3 头 INT8 模型可检出人，conf 0.831**
- [x] 推理 18.3 FPS，端到端 13.7 FPS
- [x] 与 ONNX 的框 **IoU 0.9916**，score 0.808 vs 0.831
- [ ] 冲 30 FPS（后处理优化 / C++ / 更小输入）
- [ ] 相机到货后的实拍验证
