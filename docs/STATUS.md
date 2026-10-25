# 当前状态

> **每次收工前更新这里。** 这是跨机器唯一的"记忆"，不写就等于丢。
> 格式：写结论，不写过程流水账。

最后更新：2026-10-25 · Mac（补 Mac 环境采集；Windows 内容未动）

## 仓库同步状态

- 远端 `origin/main` 已与本地合并（以远端为基线，Windows 侧文件叠加在上，历史线性）。
- **唯一远端：GitHub** `git@github.com:cbt0PVE/MyDrone.git`。Gitee 镜像已取消，不再推送。
- 2026-10-25 Mac 侧发现本地 `origin` 下仍挂着 Gitee 的第二条 `url`（`git push` 会同时推到 Gitee），已删除；现在 `git remote -v` 只有 GitHub。其他机器 `git remote -v` 也顺手核对一遍。
- 备份分支 `backup/windows-init` 仅存在于 Windows 本地，未推送，确认无误后可删。
- 新开对话的交接说明：`docs/AI_CONTEXT.md`（整段粘贴即可）。

## 阶段

**阶段 0：链路与参数确认（进行中，未写新代码）**

## 已完成

- 通读现有三个脚本，结论见 `docs/CODE_NOTES.md`（未改代码）。
- 采集 Windows 环境事实，见 `docs/ENV.md` A 节。
- 2026-10-25 采集 Mac 环境事实，见 `docs/ENV.md` B 节：macOS 27.0.1 arm64、系统 Python 3.9.6（依赖装在用户 site-packages，无 venv）、mavsdk 3.15.3 与 torch 2.8.0/MPS 可用。
- Mac 定位已澄清：**只用来写文档/日志、改代码，不维护仿真环境**。SITL/jMAVSim 的缺口（缺 JDK 17）只作存档，不是待办。
- 建立仓库结构与跨机器同步约定。

## 正在做

- RC 通道映射：QGC → Radio 页，逐个拨 6 个开关，记录通道号与档位（两段/三段）。
  - 需要产出：`CH?=开关?（两段/三段）` 的对应表。
  - 有了它才能定 `RC_MAP_OFFB_SW`。

## 待确认（别当结论用）

1. `COM_RC_OVERRIDE` 在你这版 PX4 里是否位掩码（bit1=OFFBOARD）？设 1 可能只对 AUTO 生效。
2. `COM_RC_IN_MODE` 当前值——之前"禁用遥控器"改的很可能就是它。
3. `RC_STICK_DZ` 默认是否已是 0.1（若是，调到 0.15 收益很小）。
4. 静置不碰杆时，QGC Radio 页各通道数值是否稳定在 1500（判断是死区问题还是通道/信号问题）。

## 下一步

1. 完成通道映射，填进 `docs/PX4_PARAMS.md`。
2. 按 `docs/PX4_PARAMS.md` 清单核参数，记录旧值。
3. 决定是否先写一个只读 RC 通道监视脚本（不碰动力，打印通道值与抖动幅度）。

## 环境提醒

- Windows 用 conda `drone` 环境（Python 3.10 + mavsdk 3.15.3），别用 base。
- Mac 已采集（`docs/ENV.md` B 节）：`python3` = 系统 3.9.6，依赖在用户 site-packages；PX4 检出在 `~/Developer/DroneProject/PX4-Autopilot`（shallow，无 tag）。**Mac 不修仿真环境**，SITL/jMAVSim 仅存档；不要在这台机器上开工飞行脚本。
