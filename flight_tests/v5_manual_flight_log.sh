#!/usr/bin/env bash
# v5：只记录，不控飞机。用遥控器手动做基础飞行（前进/后退/转弯/降落）。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-serial:///dev/ttyACM0:115200}"
cd "$DIR/.."
exec python3 rc_flight_log.py --port "$PORT"
