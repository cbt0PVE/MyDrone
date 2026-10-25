import asyncio
from mavsdk import System

async def main():
    drone = System()
    
    # 你的数传所在端口是 COM5，出厂波特率为 57600
    print(">>> 正在打开数传端口 serial://COM5:57600 ...")
    await drone.connect(system_address="serial://COM5:57600")

    print(">>> 等待飞控心跳包（建立连接中）...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("[√] 飞控连接成功！软硬件链路已打通！")
            break

    # 读取并显示一次电池状态
    print(">>> 正在读取机体状态...")
    async for battery in drone.telemetry.battery():
        voltage = round(battery.voltage_v, 2)
        remaining = round(battery.remaining_percent * 100, 1)
        print(f"[电池] 当前电压: {voltage} V, 剩余: {remaining}%")
        break

    # 读取当前飞行模式
    async for flight_mode in drone.telemetry.flight_mode():
        print(f"[状态] 当前飞行模式: {flight_mode}")
        break

    print(">>> 基础通信测试完成！")

if __name__ == "__main__":
    asyncio.run(main())
