#!/usr/bin/env bash
# v1：1.0m 悬停 5 秒；悬停基准 0.19（实测 0.17-0.18 才离地）。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.0 5 0.19 0.05
