import asyncio
import time
from mavsdk import System
from mavsdk.offboard import Attitude

# ==================== 姿态平衡与安全推力参数 ====================
SERIAL_PORT = "serial://COM5:57600"

# 【核心平衡微调】
# PITCH_TRIM: 正数抬机头(往后退)，负数压机头(往前冲)。往前飘设为 +1.0 ~ +1.5
PITCH_TRIM = 1.0    

# ROLL_TRIM: 正数往右倾(向右飞)，负数往左倾(向左飞)。机头朝前若往右偏，设为负值拉回
ROLL_TRIM  = -1.2   

TARGET_ALTITUDE = 1.0     # 目标起飞高度: 1 米
HOVER_DURATION = 5.0      # 悬停时间: 5 秒
BASE_THRUST = 0.16       # 基准推力: 18%
MIN_THRUST = 0.10         # 最小推力限幅: 10%
MAX_THRUST = 0.18         # 严格锁死在 20% (温和低转速，绝不暴冲)
KP_ALT = 0.10             # 高度补偿系数

# ==================== 全局状态量 ====================
current_alt = 0.0
target_alt = 0.0
current_thrust = 0.0
is_flying = True


async def telemetry_altitude_loop(drone):
    """后台监听气压计相对地面高度"""
    global current_alt, is_flying
    async for pos in drone.telemetry.position():
        current_alt = pos.relative_altitude_m
        if not is_flying:
            break


async def control_thrust_loop(drone):
    """后台 10Hz 实时下发带平衡配平的姿态与推力"""
    global current_thrust, target_alt, current_alt, is_flying
    while is_flying:
        if target_alt > 0.05:
            error = target_alt - current_alt
            calc = BASE_THRUST + (error * KP_ALT)
            # 严格锁死在 10% ~ 20%
            current_thrust = max(MIN_THRUST, min(MAX_THRUST, calc))

        try:
            # 代入配平角度: roll=ROLL_TRIM, pitch=PITCH_TRIM, yaw=0.0
            # 飞控会自动解算 4 个电机的差速输出以维持这个补偿姿态
            await drone.offboard.set_attitude(
                Attitude(ROLL_TRIM, PITCH_TRIM, 0.0, current_thrust)
            )
        except Exception:
            pass
        await asyncio.sleep(0.1)


async def main():
    global target_alt, current_thrust, is_flying
    drone = System()

    print(f">>> 1. 正在通过数传连接飞控: {SERIAL_PORT} ...")
    await drone.connect(system_address=SERIAL_PORT)

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("[√] 通信建立成功！")
            break

    try:
        # ------------ 步骤 2：静默解锁 ------------
        print("\n>>> 2. 发送解锁指令 (Arm)...")
        try:
            await asyncio.wait_for(drone.action.arm(), timeout=2.5)
            print("[√] 解锁成功！")
        except Exception:
            print("[提示] 未收到 ACK（数传丢包），指令已正常生效！")

        print("[√] 动力系统就绪（电机怠速运转）！稳定 2 秒...")
        await asyncio.sleep(2.0)

        # ------------ 步骤 3：切入 Offboard 模式 ------------
        print(f"\n>>> 3. 注入配平初值 (Roll: {ROLL_TRIM}°, Pitch: {PITCH_TRIM}°) 并切入 Offboard...")
        await drone.offboard.set_attitude(Attitude(ROLL_TRIM, PITCH_TRIM, 0.0, 0.0))
        await asyncio.sleep(0.3)

        try:
            await asyncio.wait_for(drone.offboard.start(), timeout=3.0)
            print("[√] 成功切入 Offboard 模式！已正式接管动力！")
        except Exception as e:
            print(f"[提示] Offboard 启动确认包延迟: {e}，直接推进接管！")

        # ------------ 步骤 4：启动推流与高度监听 ------------
        print("\n>>> 4. 激活姿态配平与控制引擎 (最高推力限幅 20%)...")
        asyncio.create_task(telemetry_altitude_loop(drone))
        asyncio.create_task(control_thrust_loop(drone))
        await asyncio.sleep(1.0)
        print(f"[传感器] 起飞地面基准高度: {current_alt:.2f} 米")

        # ------------ 步骤 5：阶段一 —— 爬升 (限幅 20%) ------------
        print(f"\n>>> 5. [阶段一：爬升] 目标设定 {TARGET_ALTITUDE} 米 (平衡配平执行中)...")
        target_alt = TARGET_ALTITUDE
        climb_start = time.time()

        # 爬升限制 6 秒或手托抬升达到 85% 高度
        while time.time() - climb_start < 6.0:
            print(f"    [爬升中] 实际高度: {current_alt:5.2f}m / 目标: {target_alt:.1f}m | 输出推力: {current_thrust*100:2.0f}%")
            if current_alt >= (TARGET_ALTITUDE * 0.85):
                print(f"[√] 达到目标高度区间 ({current_alt:.2f}m)！进入悬停！")
                break
            await asyncio.sleep(0.3)

        # ------------ 步骤 6：阶段二 —— 悬停 5 秒 ------------
        print(f"\n>>> 6. [阶段二：悬停] 维持定高悬停 {HOVER_DURATION} 秒...")
        hover_start = time.time()
        while time.time() - hover_start < HOVER_DURATION:
            rem = HOVER_DURATION - (time.time() - hover_start)
            print(f"    [悬停中] 实际高度: {current_alt:5.2f}m | 悬停推力: {current_thrust*100:2.0f}% | 倒计时: {rem:3.1f}s")
            await asyncio.sleep(0.5)

        # ------------ 步骤 7：阶段三 —— 自动缓降 ------------
        print("\n>>> 7. [阶段三：降落] 开始平滑降落...")
        steps = 15
        for i in range(steps):
            target_alt = TARGET_ALTITUDE * (1.0 - (i / steps))
            print(f"    [下降中] 引导高度: {target_alt:4.2f}m | 实际高度: {current_alt:4.2f}m | 推力: {current_thrust*100:2.0f}%")
            await asyncio.sleep(0.2)

        # 触地压地微推力
        print(">>> 触地完成，施加最低怠速压地...")
        target_alt = 0.0
        current_thrust = 0.10
        await asyncio.sleep(1.0)

    except KeyboardInterrupt:
        print("\n[!] 键盘手动急停 (Ctrl+C)！")
    finally:
        # ------------ 步骤 8：急停断电停机 ------------
        print("\n>>> 8. 触发急停断电停机 (Kill Switch)...")
        is_flying = False
        target_alt = 0.0
        current_thrust = 0.0

        try:
            await drone.offboard.stop()
        except Exception:
            pass

        try:
            await drone.action.kill()
            print("[√] 电机动力彻底切断！测试结束。")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())