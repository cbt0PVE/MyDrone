#!/usr/bin/env bash
# v3：只记录，不控飞机。遥控器手动做基础飞行。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-serial:///dev/ttyACM0:115200}"
cd "$DIR/.."
exec python3 rc_flight_log.py --port "$PORT"
