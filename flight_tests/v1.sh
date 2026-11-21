#!/usr/bin/env bash
# v1：1.0m 悬停 5 秒。
# 起飞助推 22%（仅低于 0.25m 或前 2 秒），之后回 0.14。
# 低电量不要飞；充满电再用。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec env BOOST_THRUST=0.22 BOOST_ALT=0.25 BOOST_SEC=2.0 \
  "$DIR/common.sh" 1.0 5 0.14 0.05
