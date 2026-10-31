#!/usr/bin/env bash
# 一键跑 SITL 视觉闭环（在 WSL 里执行）：
#   bash sim/run.sh                 # 默认跑 25 秒后自动降落
#   bash sim/run.sh --duration 60   # 自己传参数给 run_tracking.py
#
# 为什么全部塞进一个脚本：每次 wsl.exe 调用是独立会话，脚本一退，后台的
# PX4/Gazebo 会被一起带走。所以「起仿真 → 等就绪 → 跑闭环 → 收尾」必须
# 在同一个进程树里完成（这个坑踩过两次，见 docs/STATUS.md）。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4_DIR="${PX4_DIR:-$HOME/src/PX4-Autopilot}"
WORLD="${PX4_GZ_WORLD:-mydrone_track}"
LOG="${SITL_LOG:-/tmp/sitl.log}"
READY_TIMEOUT="${READY_TIMEOUT:-90}"

SITL_PGID=""
cleanup() {
  # 别用 pkill -f 宽匹配：它会把 WSL 会话里别的进程一起带走，
  # 实测会让下一次 wsl.exe 调用直接 E_UNEXPECTED。
  # 这里只对"我们自己起的那个进程组"发信号：先 TERM，等它自己收尾，再 KILL。
  if [ -n "$SITL_PGID" ]; then
    kill -TERM -"$SITL_PGID" 2>/dev/null
    for _ in $(seq 10); do
      kill -0 -"$SITL_PGID" 2>/dev/null || break
      sleep 0.5
    done
    kill -KILL -"$SITL_PGID" 2>/dev/null
  fi
  sleep 2
}
trap cleanup EXIT

if [ ! -d "$PX4_DIR" ]; then
  echo "[sim] 找不到 PX4：$PX4_DIR（用 PX4_DIR=... 指定）"
  exit 1
fi
if [ ! -e "$PX4_DIR/Tools/simulation/gz/worlds/$WORLD.sdf" ]; then
  echo "[sim] 世界 $WORLD 还没接上，先跑一次：bash sim/setup.sh"
  exit 1
fi

: > "$LOG"
cd "$PX4_DIR" || exit 1
export PX4_GZ_WORLD="$WORLD"
export HEADLESS=1
# setsid：让 make 自成进程组，这样收尾时能整组精确回收，
# 不会误伤本脚本或 WSL 会话里的其它进程。
setsid make px4_sitl gz_x500_mono_cam </dev/null >>"$LOG" 2>&1 &
SITL_PGID=$!
echo "[sim] SITL 启动中（world=$WORLD，日志 $LOG，进程组 $SITL_PGID）"

# 1) 等世界就绪：PX4 自己和 Gazebo 的握手判据就是这个服务
ready=0
for i in $(seq "$READY_TIMEOUT"); do
  if gz service -i --service "/world/$WORLD/scene/info" 2>&1 | grep -q "Service providers"; then
    echo "[sim] 世界就绪（${i}s）"
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "[sim] 世界 ${READY_TIMEOUT}s 未就绪，日志尾部："
  tr -d '\r' < "$LOG" | grep -av '^pxh>' | tail -20
  exit 1
fi

# 2) 等相机出帧（话题出现 ≠ 已经有帧，所以再等一小段）
for _ in $(seq 30); do
  if gz topic -l 2>/dev/null | grep -q '/sensor/camera/image'; then
    break
  fi
  sleep 1
done
sleep 2

# 3) 跑闭环
cd "$REPO" || exit 1
exec_args=(--sitl --duration 25)
if [ "$#" -gt 0 ]; then
  # 用户传了参数就以用户的为准，但 --sitl 是这套脚本的前提，始终带上
  exec_args=(--sitl "$@")
fi
echo "[sim] 运行 run_tracking.py ${exec_args[*]}"
python3 run_tracking.py "${exec_args[@]}"
rc=$?
echo "[sim] run_tracking 退出码 $rc"
exit $rc
