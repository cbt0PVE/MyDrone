#!/usr/bin/env bash
# 把 MyDrone 的仿真资产接到 PX4 的 Gazebo 资源目录上。
#
# 为什么用符号链接而不是复制：PX4 的 worlds 目录只认「文件名」，而我们希望
# 世界文件和模型留在仓库里（另一台机器 git pull 就有一份一致的资产）。
# 链接可逆，不污染 PX4 的 git 工作区。
#
# 用法：bash sim/setup.sh          # 建链
#       bash sim/setup.sh --clean  # 拆链
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PX4="${PX4_DIR:-$HOME/src/PX4-Autopilot}"
STORE="$PX4/Tools/simulation/gz"
WORLD_NAME="mydrone_track"
PERSON="MaleVisitorPhone"
FUEL="https://fuel.gazebosim.org/1.0/OpenRobotics/models/$PERSON/tip/files"

if [ ! -d "$STORE/worlds" ]; then
  echo "[setup] 找不到 $STORE/worlds"
  echo "[setup] 先跑一次 make px4_sitl gz_x500_mono_cam，让 PX4 把 gazebo 模型下载好"
  exit 1
fi

if [ "${1:-}" = "--clean" ]; then
  rm -f "$STORE/worlds/$WORLD_NAME.sdf"
  rm -f "$STORE/models/$PERSON"
  echo "[setup] 已拆除链接"
  exit 0
fi

# 1) 行人模型：从 Fuel 下载到 sim/assets（不入库）
DEST="$REPO/sim/assets/models/$PERSON"
mkdir -p "$DEST/meshes"
fetch() {
  local f="$1"
  [ -s "$DEST/$f" ] && return 0
  for _ in 1 2 3; do
    if curl -sf --max-time 180 "$FUEL/$f" -o "$DEST/$f"; then
      echo "[setup] 下载 $f ($(stat -c%s "$DEST/$f") B)"
      return 0
    fi
    sleep 1
  done
  echo "[setup] 下载失败：$f"
  return 1
}
for f in model.config model.sdf \
         meshes/MaleVisitorPhoneWalk.dae \
         meshes/MaleVisitorPhoneIdle.dae \
         meshes/MaleVisitorPhoneWalkToIdle.dae \
         meshes/MaleVisitorPhoneIdleToWalk.dae \
         meshes/MaleVisitorPhone_Diffuse.png; do
  fetch "$f"
done

# 2) 建链
ln -sfn "$DEST" "$STORE/models/$PERSON"
ln -sfn "$REPO/sim/worlds/$WORLD_NAME.sdf" "$STORE/worlds/$WORLD_NAME.sdf"

echo "[setup] 就绪。启动："
echo "        PX4_GZ_WORLD=$WORLD_NAME make px4_sitl gz_x500_mono_cam"
echo "[setup] 节点校验："
ls -l "$STORE/worlds/$WORLD_NAME.sdf" "$STORE/models/$PERSON"
