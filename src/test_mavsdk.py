import asyncio
from mavsdk import System

async def main():
    # 1. 初始化 MAVSDK 无人机核心对象
    drone = System()
    
    print("📡 正在连接 PX4 虚拟飞控 (UDP 端口: 14540)...")
    # 仿真时，PX4 SITL 默认会向本地 14540 端口广播 MAVLink 数据流
    await drone.connect(system_address="udp://:14540")

    # 2. 异步监听连接状态
    print("⏳ 等待无人机建立心跳握手...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✅ 成功与飞控建立通信链路！")
            break

    # 3. 航前安全健康检查 (GPS 锁死验证)
    print("🛰️ 正在检查 GPS 全球定位状态...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("✅ GPS 状态健康，满足 Offboard 飞行条件！")
            break

    # 4. 触发解锁 (ARM)
    print("🔌 正在解锁虚拟电机...")
    try:
        await drone.action.arm()
        print("🚀 电机已解锁！转速正常。")
    except Exception as e:
        print(f"❌ 解锁失败: {e}")
        return

    # 5. 自动起飞测试
    print("🛫 正在发送起飞指令 (Takeoff)...")
    await drone.action.takeoff()
    
    # 悬停等待 5 秒，让你在仿真器里看清飞机的姿态
    await asyncio.sleep(5)

    # 6. 安全自主降落
    print("🛬 测试完毕，正在自主降落 (Land)...")
    await drone.action.land()
    print("🏁 无人机已安全着陆。")

if __name__ == "__main__":
    # 启动异步事件循环
    asyncio.run(main())