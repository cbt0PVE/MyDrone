# -*- coding: utf-8 -*-
"""在香橙派上跑 RKNN 推理基准（不需要摄像头）。

    python3 tools/bench_rknn.py --model best.rknn --runs 50

输出：输入/输出形状、单帧耗时、FPS、输出是否 NaN。
"""

import argparse
import time

import numpy as np


def main():
    ap = argparse.ArgumentParser(description="RKNN 板上推理基准")
    ap.add_argument("--model", required=True, help=".rknn 路径")
    ap.add_argument("--runs", type=int, default=50, help="计时轮数，默认 50")
    ap.add_argument("--size", type=int, default=640, help="输入边长，默认 640")
    ap.add_argument("--core", default="NPU_CORE_0_1_2", help="NPU 核掩码")
    args = ap.parse_args()

    from rknnlite.api import RKNNLite

    core = getattr(RKNNLite, args.core, None)
    if core is None:
        raise SystemExit(f"未知 core: {args.core}")

    rknn = RKNNLite()
    ret = rknn.load_rknn(args.model)
    if ret != 0:
        raise SystemExit(f"load_rknn 失败: {ret}")
    ret = rknn.init_runtime(core_mask=core)
    if ret != 0:
        raise SystemExit(f"init_runtime 失败: {ret}（驱动/运行时版本可能不匹配）")

    blob = np.random.rand(1, 3, args.size, args.size).astype(np.float32)
    outputs = rknn.inference(inputs=[blob], data_format="nchw")
    print("output shapes:", [tuple(o.shape) for o in outputs])
    print("output dtypes:", [o.dtype for o in outputs])

    # warmup
    for _ in range(5):
        rknn.inference(inputs=[blob], data_format="nchw")

    times = []
    for _ in range(args.runs):
        t0 = time.perf_counter()
        rknn.inference(inputs=[blob], data_format="nchw")
        times.append((time.perf_counter() - t0) * 1000.0)

    avg = sum(times) / len(times)
    print(f"runs={len(times)} avg={avg:.2f} ms  min={min(times):.2f}  max={max(times):.2f}")
    print(f"fps={1000.0 / avg:.1f}")

    out = outputs[0]
    print("nan:", bool(np.isnan(out).any()), "inf:", bool(np.isinf(out).any()))
    rknn.release()


if __name__ == "__main__":
    main()
