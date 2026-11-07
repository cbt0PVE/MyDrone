# -*- coding: utf-8 -*-
"""ONNX -> RKNN 转换（在 x86_64 Linux / WSL 上跑，不要在板子上跑）。

    python tools/make_rknn_dataset.py \
        --images datasets/coco_person/images/train --limit 100 --output /tmp/rknn_dataset.txt

    python tools/convert_rknn.py \
        --onnx runs/detect/runs/detect/coco_person/weights/best.onnx \
        --dataset /tmp/rknn_dataset.txt \
        --output runs/detect/runs/detect/coco_person/weights/best.rknn

说明：
- `rknn-toolkit2` 只支持 x86_64 Linux；板子上只装 `rknn-toolkit-lite2`。
- 量化集用 100–200 张有人的图；不要只拿单人特写，场景要接近飞行画面。
- 输入归一化：ultralytics 的 ONNX 期望 RGB、0–1；这里 mean=0、std=255。
- 如果 INT8 掉点明显，先用 `--no-quant` 出 FP16 对照，再扩量化集。
"""

import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="ONNX -> RKNN（x86_64 Linux）")
    ap.add_argument("--onnx", required=True, help="输入 ONNX")
    ap.add_argument("--output", required=True, help="输出 .rknn")
    ap.add_argument("--dataset", default="", help="量化图片列表（每行一个路径）")
    ap.add_argument("--target", default="rk3588", help="目标平台，默认 rk3588")
    ap.add_argument("--no-quant", action="store_true", help="不做 INT8 量化（FP16）")
    ap.add_argument("--quant-algorithm", default="normal",
                    choices=["normal", "mmse", "kl_divergence"],
                    help="INT8 量化算法；分类头被压坏时可试 mmse")
    ap.add_argument("--quant-dtype", default="w8a8",
                    choices=["w8a8", "w8a16"],
                    help="w8a8=纯 INT8；w8a16=权重 int8、激活 fp16，分类头更稳")
    ap.add_argument("--hybrid-level", type=int, default=0, choices=[0, 1, 2, 3],
                    help="自动混合量化级别；1=把敏感层保留浮点")
    ap.add_argument("--opt-level", type=int, default=3, choices=[0, 1, 2, 3],
                    help="优化级别；0=关掉输出优化，排查输出 int8 问题")
    ap.add_argument("--rgb2bgr", action="store_true",
                    help="量化图按 RGB->BGR 处理；颜色顺序不对会把分类头校准坏")
    ap.add_argument("--heads", action="store_true",
                    help="只输出 3 个检测头（DFL/分类后处理放 Python），避免全模型 INT8 分类头塌陷")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.onnx):
        sys.exit(f"ONNX 不存在: {args.onnx}")
    if not args.no_quant and not args.dataset:
        sys.exit("INT8 量化需要 --dataset；只想出 FP16 就加 --no-quant")
    if args.dataset and not os.path.exists(args.dataset):
        sys.exit(f"量化列表不存在: {args.dataset}")

    try:
        from rknn.api import RKNN
    except ImportError as e:
        sys.exit(
            "需要 rknn-toolkit2（x86_64 Linux）：\n"
            "  pip install rknn-toolkit2==2.3.2\n"
            f"原始错误: {e}"
        )

    rknn = RKNN(verbose=args.verbose)
    try:
        print(f"[1/4] config target={args.target}")
        rknn.config(
            mean_values=[[0.0, 0.0, 0.0]],
            std_values=[[255.0, 255.0, 255.0]],
            target_platform=args.target,
            quantized_algorithm=args.quant_algorithm,
            quantized_dtype=args.quant_dtype,
            quant_img_RGB2BGR=args.rgb2bgr,
            optimization_level=args.opt_level,
            quantized_hybrid_level=args.hybrid_level,
        )

        print(f"[2/4] load_onnx {args.onnx}")
        if args.heads:
            outputs = [
                "/model.22/cv2.0/cv2.0.2/Conv_output_0",
                "/model.22/cv3.0/cv3.0.2/Conv_output_0",
                "/model.22/cv2.1/cv2.1.2/Conv_output_0",
                "/model.22/cv3.1/cv3.1.2/Conv_output_0",
                "/model.22/cv2.2/cv2.2.2/Conv_output_0",
                "/model.22/cv3.2/cv3.2.2/Conv_output_0",
            ]
            ret = rknn.load_onnx(model=args.onnx, outputs=outputs)
        else:
            ret = rknn.load_onnx(model=args.onnx)
        if ret != 0:
            sys.exit(f"load_onnx 失败: {ret}")

        print(f"[3/4] build quant={not args.no_quant} dataset={args.dataset or '-'}")
        ret = rknn.build(
            do_quantization=not args.no_quant,
            dataset=args.dataset if not args.no_quant else None,
        )
        if ret != 0:
            sys.exit(f"build 失败: {ret}")

        out_dir = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(out_dir, exist_ok=True)
        print(f"[4/4] export_rknn {args.output}")
        ret = rknn.export_rknn(args.output)
        if ret != 0:
            sys.exit(f"export_rknn 失败: {ret}")

        size = os.path.getsize(args.output)
        print(f"OK {args.output} ({size / 1e6:.2f} MB)")
    finally:
        try:
            rknn.release()
        except Exception:
            pass


if __name__ == "__main__":
    main()
