import argparse
import asyncio
from mavsdk import System


async def main(port):
    drone = System()

    # 飞控 USB 直连：COM6，115200
    print(f">>> 正在打开飞控端口 {port} ...")
    await drone.connect(system_address=port)

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
    ap = argparse.ArgumentParser(description="MAVSDK 飞控连接测试")
    ap.add_argument("--port", default="serial://COM6:115200",
                    help="飞控 USB: serial://COM6:115200；数传: serial://COM5:57600")
    asyncio.run(main(ap.parse_args().port))
