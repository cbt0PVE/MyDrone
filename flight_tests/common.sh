#!/usr/bin/env bash
# 通用试飞包装：所有版本都走 hover_test.py，参数由版本脚本传入。
# 额外参数可用 EXTRA_ARGS，例如：EXTRA_ARGS="--no-arm" bash v1_1m_5s.sh
set -euo pipefail

PORT="${PORT:-serial:///dev/ttyACM0:115200}"
ALT="${1:-1.0}"
HOLD="${2:-5}"
THRUST="${3:-0.14}"
KP="${4:-0.05}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

BOOST_ARGS=""
if [ -n "${BOOST_THRUST:-}" ]; then
  BOOST_ARGS="--boost-thrust ${BOOST_THRUST} --boost-alt ${BOOST_ALT:-0.25} --boost-sec ${BOOST_SEC:-2.0}"
fi

cd "$(dirname "$0")/.."

echo "=============================================="
echo " 试飞版本参数"
echo "   port   : $PORT"
echo "   alt    : ${ALT} m"
echo "   hold   : ${HOLD} s"
echo "   thrust : ${THRUST}"
echo "   kp     : ${KP}"
echo "   extra  : ${EXTRA_ARGS:-无}"
echo "   boost  : ${BOOST_ARGS:-无}"
echo "=============================================="
echo " 安全：先手托/系留；RC 全程在手；桨已检查。"
echo "=============================================="

# shellcheck disable=SC2086
exec python3 hover_test.py \
  --port "$PORT" \
  --alt "$ALT" \
  --hold "$HOLD" \
  --hover-thrust "$THRUST" \
  --kp "$KP" \
  ${BOOST_ARGS} \
  ${EXTRA_ARGS}
