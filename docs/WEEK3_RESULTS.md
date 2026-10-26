# 第 3 周训练结果（YOLOv8n · 单类 person）

> 2026-10-27 实跑产出，可直接作为中期验收素材。

## 一、结论

| 指标 | 数值 |
| --- | --- |
| mAP@0.5 | **0.7526** |
| mAP@0.5:0.95 | **0.4983** |
| 训练设备 | RTX 4060 Laptop（CUDA） |
| 耗时 | 50 epoch 约 18 分钟 |

**推理速度（RTX 4060）**

| 格式 | 单张耗时 | 吞吐 |
| --- | --- | --- |
| PyTorch `best.pt`（GPU） | 15.1 ms | **66.3 FPS** |
| ONNX Runtime（CPU） | 21.9 ms | 45.7 FPS |

## 二、数据集

- 来源：**COCO val2017**（5000 张）过滤出含 person 的图
- 过滤条件：`category_id == 1`、非 `iscrowd`、框高 ≥ 40px、框宽 ≥ 16px
- 划分：训练 2125 张 / 验证 374 张（85:15）
- 标注总数：验证集上 1123 个 person 实例
- 磁盘：386MB

生成命令：

```powershell
python tools/prepare_coco_person.py
```

## 三、训练配置

```text
起点权重  yolov8n.pt（COCO 预训练，80 类 → 覆盖为 1 类）
epochs    50
imgsz     640
batch     16
优化器    AdamW（ultralytics auto 选择），lr0=0.002
mosaic    0.5，最后 5 轮关闭
```

关键产物路径（注意叠了一层）：
`runs/detect/runs/detect/coco_person/weights/{best.pt, best.onnx}`

> 这个嵌套是脚本里 `project="runs/detect"` 撞上 ultralytics 默认值导致的，
> 已在新版本脚本里改成 `project="runs"`，下次跑会落在 `runs/coco_person/`。

## 四、图表

| 文件 | 内容 |
| --- | --- |
| `docs/figs/train_results.png` | 损失与 mAP 随 epoch 曲线 |
| `docs/figs/box_pr_curve.png` | PR 曲线（报告里最常用的一张） |
| `docs/figs/confusion_matrix.png` | 归一化混淆矩阵 |

mAP 曲线在 50 轮末尾仍在缓慢上升，说明**再加 epoch 还有收益**，但边际递减。
课程交付用现在的数字已经够；如果要做对比实验，可以跑 100 轮看能到多少。

## 五、报告里必须写清楚的两件事

1. **这是单类模型**（只有 person），mAP 不能和 COCO 80 类的公开榜单直接比较。
   公开的 YOLOv8n 全类 mAP@0.5 约 0.37，我们 0.75 看着高，是因为任务简单了。
2. **这是 COCO 验证集上训、验证集上评**，两者同分布。
   真实部署场景（你的室内 / 人群 / 逆光）会有明显掉点，必须自采数据复测。

## 六、下一步

- [ ] 用 `best.onnx` + `rknn-toolkit2` 转 INT8（需要香橙派到位或先在 WSL 里验证）
- [ ] 准备 100–200 张**校准图**：从实际飞行场景抽，覆盖不同光照和距离
- [ ] 上板测 FPS，与 4060 的 66 FPS 对比，记录掉点情况
- [ ] 把检测器接到 `vnav`：`YoloDetector` 实现 `Detection` 接口（见 `docs/ROADMAP.md` 第四节）
