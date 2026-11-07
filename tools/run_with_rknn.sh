#!/usr/bin/env bash
# Run any command with the matching librknnrt.so bind-mounted over /usr/lib/librknnrt.so.
# User-level: uses an unprivileged mount namespace, no sudo, does not modify the system.
#
#   bash run_with_rknn.sh python3 bench_rknn.py --model best.rknn
#
# Why: the board image ships librknnrt 1.4.0, but RKNN Toolkit2 2.3.2 models need
# runtime 2.3.2. rknnlite loads /usr/lib/librknnrt.so by absolute path, so
# LD_LIBRARY_PATH/LD_PRELOAD alone do not override it.
set -euo pipefail

RUNTIME="${RKNN_RUNTIME:-$HOME/.local/lib/rknn/librknnrt.so}"
if [ ! -f "$RUNTIME" ]; then
    echo "找不到 RKNN runtime: $RUNTIME" >&2
    echo "把匹配版本的 librknnrt.so 放到该路径，或设置 RKNN_RUNTIME" >&2
    exit 1
fi
if [ "$#" -lt 1 ]; then
    echo "用法: bash run_with_rknn.sh <command> [args...]" >&2
    exit 2
fi

exec unshare -r -m bash -c '
    mount --bind "$0" /usr/lib/librknnrt.so || {
        echo "bind mount 失败：内核可能禁用了 unprivileged user namespace" >&2
        exit 3
    }
    exec "$@"
' "$RUNTIME" "$@"
