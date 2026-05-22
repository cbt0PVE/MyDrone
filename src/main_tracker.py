import asyncio
import cv2
import numpy as np
from mavsdk import System
# 💡 核心修复：新版 MAVSDK 正确的 Offboard 速度控制类导入路径
from mavsdk.offboard import VelocityNedYaw, OffboardError

# 📐 视觉伺服 PID 核心控制器参数
Kp = 0.005
Kd = 0.001
last_error_x = 0

async def perception_loop(drone):
    """ 👁️ 视觉感知与 🚀 飞控控制高频合流回路 """
    global last_error_x
    
    # 初始化 Mac 摄像头
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 感知错误: 无法打开 Mac 摄像头")
        return

    print("🎯 [AI 视觉追踪外环]：算法激活成功，开始捕获目标...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.01)
            continue
        
        # 镜像画面
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        
        # 色彩解耦转换
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # ---------------------------------------------------------------
        # 🎯 黄色鸭舌帽核心 HSV 过滤区间（根据你之前的测试数据微调）
        # ---------------------------------------------------------------
        lower_yellow = np.array([11, 43, 46])
        upper_yellow = np.array([34, 255, 255])
        
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        # 形态学滤波消噪
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        # 计算几何矩解算质心
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        error_x = 0
        target_detected = False
        
        if contours:
            max_contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(max_contour) > 500:
                M = cv2.moments(max_contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    # 解算出当前帽子离屏幕中心的像素偏差
                    error_x = cx - (w // 2)
                    target_detected = True
                    
                    # 绘制靶心
                    cv2.circle(frame, (cx, int(M["m01"] / M["m00"])), 10, (0, 0, 255), -1)

        # 绘制中心参考十字线
        cv2.line(frame, (w // 2, h // 2 - 20), (w // 2, h // 2 + 20), (255, 255, 255), 2)
        cv2.line(frame, (w // 2 - 20, h // 2), (w // 2 + 20, h // 2), (255, 255, 255), 2)
        
        # 双视窗堆叠显示
        mask_3ch = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        display_img = np.hstack((frame, mask_3ch))
        cv2.imshow("MyDrone AI - Unified Tracker Loop", display_img)

        # 📐 如果抓到了帽子，执行 PD 控制律并高频注入虚拟飞控
        if target_detected:
            derivative = error_x - last_error_x
            # 计算横向平移速度 (偏右输出正速度向右飞，偏左输出负速度向左飞)
            output_velocity_y = Kp * error_x + Kd * derivative
            last_error_x = error_x
            
            # 限速保护：防止画面突变导致飞机突变暴走，最大平移速度限制在 ±1.5 m/s
            output_velocity_y = max(-1.5, min(1.5, output_velocity_y))
            
            # 发送控制向量给 PX4 (前向速度0.0, 右向速度output_velocity_y, 下向速度0.0, 偏航角0.0)
            try:
                await drone.offboard.set_velocity_ned(
                    VelocityNedYaw(0.0, output_velocity_y, 0.0, 0.0)
                )
            except Exception as e:
                print(f"⚠️ 注入 Offboard 速度失败: {e}")
        else:
            # 如果没看到帽子，保持原地悬停速度为 0
            try:
                await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
            except Exception:
                pass
        # 允许 OpenCV 窗体刷新，按 'q' 键退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("🏁 用户主动终止追踪系统。")
            break
            
        # 释放 10ms CPU 给协程调度器，保持 100Hz 的控制外环高频吞吐
        await asyncio.sleep(0.01)

    cap.release()
    cv2.destroyAllWindows()

async def main():
    drone = System()
    print("📡 正在连接 PX4 虚拟飞控...")
    await drone.connect(system_address="udp://:14540")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✅ 跨语言网络套接字通信打通！")
            break

    print("⏳ 等待无人机 GPS 状态对齐...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("✅ 航前体检通过！")
            break

    print("🔌 解锁电机中...")
    await drone.action.arm()

    print("🛫 自动起飞至 2 米安全悬停高度...")
    await drone.action.takeoff()
    await asyncio.sleep(12)  # 静止悬停 5 秒稳住气流

    print("🔄 [控制权移交]：正在切入 Offboard 模式...")
    # 进入 Offboard 前必须先发送一个零速度占位包，告诉飞控我们准备好了
    await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
    try:
        await drone.offboard.start()
        print("🚀 Offboard 模式已死锁锁死！控制权成功交由 Python AI！")
    except OffboardError as error:
        print(f"❌ 切换 Offboard 失败: {error._result.result}，正在紧急降落...")
        await drone.action.land()
        return

    # 🎬 双脑会师：把打通的飞控对象注入到 OpenCV 感知回路中
    await perception_loop(drone)

    # 退出时安全降落
    print("🛬 任务结束，正在自主降落...")
    try:
        await drone.offboard.stop()
    except Exception:
        pass
    await drone.action.land()
    print("🏁 飞机已安全着陆。")

if __name__ == "__main__":
    asyncio.run(main())