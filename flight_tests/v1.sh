#!/usr/bin/env bash
# v1：1.0m 悬停 5 秒，最短的低空验证。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.0 5 0.14 0.05
