#!/usr/bin/env bash
# v1：1.0m 悬停 5 秒；正常悬停推力 0.14，不做起飞助推。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.0 5 0.14 0.05
