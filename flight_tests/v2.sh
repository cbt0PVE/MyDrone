#!/usr/bin/env bash
# v2：1.5m 悬停 10 秒；v1 通过后再试。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.5 10 0.15 0.04
