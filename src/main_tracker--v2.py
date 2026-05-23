import asyncio
import cv2
import numpy as np
from mavsdk import System
# 💡 核心对齐：新版 MAVSDK 正确的 Offboard 速度控制类导入路径
from mavsdk.offboard import VelocityNedYaw, OffboardError

# 📐 三维视觉感知与 🚀 3D 速度向量闭环控制律
global last_error_x
last_error_x = 0

async def perception_loop(drone):
    """ 👁️ 三维视觉感知与 🚀 3D 速度向量闭环控制律 """
    global last_error_x
    
    # 引入多维度控制器的上一次误差，用于计算微分项（D）
    last_error_y = 0
    last_error_area = 0
    
    # 📐 核心多轨 PID 参数矩阵
    Kp_y = 0.004   # 横移比例
    Kd_y = 0.001
    
    Kp_x = 0.0005  # 前后比例 (根据面积偏差调节)
    
    Kp_z = 0.003   # 高度比例
    Kd_z = 0.0008

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 感知错误: 无法打开 Mac 摄像头")
        return

    # 设定基准目标参数
    TARGET_AREA = 12000  # 🎯 期望的帽子理想轮廓面积 (单位: 像素平方)
                        # 如果镜头前帽子面积小于这个值，飞机就会往前靠

    print("🎯 [AI 三维追踪矩阵全面激活]：开始执行空间全锁定...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.01)
            continue
        
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        center_x, center_y = w // 2, h // 2
        
        # HSV 核心色彩切片
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_yellow = np.array([11, 43, 46])
        upper_yellow = np.array([34, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        # 形态学去噪
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        target_detected = False
        error_x = 0
        error_y = 0
        error_area = 0
        
        if contours:
            max_contour = max(contours, key=cv2.contourArea)
            current_area = cv2.contourArea(max_contour)
            
            if current_area > 800: # 过滤杂色噪声
                M = cv2.moments(max_contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    # 解算三维核心空间误差
                    error_x = cx - center_x          # 左右偏差 (像素)
                    error_y = cy - center_y          # 上下偏差 (像素)
                    error_area = TARGET_AREA - current_area  # 前后面积偏差
                    
                    target_detected = True
                    
                    # 动态绘制追踪 UI
                    cv2.circle(frame, (cx, cy), 12, (0, 0, 255), -1)
                    cv2.putText(frame, f"Area: {int(current_area)}", (cx+15, cy), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # 绘制画面参考中心十字
        cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 1)
        cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 1)
        
        cv2.imshow("MyDrone AI - 3D Unified Tracker", frame)

        # 📐 核心算法合流：多轴控制律同步解算
        if target_detected:
            # 1. 左右横移控制 (Y轴速度)
            deriv_y = error_x - last_error_x
            out_vy = Kp_y * error_x + Kd_y * deriv_y
            last_error_x = error_x
            
            # 2. 前后纵深控制 (X轴速度)
            out_vx = Kp_x * error_area
            
            # 3. 垂直上下控制 (Z轴速度)
            # 💡 注意：图像坐标系中 cy > center_y 意味着目标在画面下方，飞机应当下降
            # PX4 中 Z 轴向下为正，所以 error_y 与 out_vz 正负号对齐
            deriv_z = error_y - last_error_y
            out_vz = Kp_z * error_y + Kd_z * deriv_z
            last_error_y = error_y
            
            # 4. 偏航转头控制 (Yaw角速度)
            # 让飞机在平移的同时，机头也微微向目标转动，增强视觉锁定的稳定性
            out_yaw = 0.005 * error_x 

            # 🛡️ 工业级多轴限速保护（安全护航）
            out_vx = max(-1.0, min(1.0, out_vx))
            out_vy = max(-1.2, min(1.2, out_vy))
            out_vz = max(-0.8, min(0.8, out_vz)) # 限制上下升降速度，防止砸地
            out_yaw = max(-30.0, min(30.0, out_yaw)) # 限制每秒最大转动角度

            # 🚀 强行注入 PX4 核心位置环
            try:
                await drone.offboard.set_velocity_ned(
                    VelocityNedYaw(out_vx, out_vy, out_vz, out_yaw)
                )
            except Exception as e:
                print(f"⚠️ 3D速度注入失败: {e}")
        else:
            # 失去目标，原地三轴死锁悬停
            try:
                await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
            except Exception:
                pass

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
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

    print("🔌 [越塔模式] 正在直接解锁电机...")
    await drone.action.arm()

    print("🛫 自动起飞至 2 米安全悬停高度...")
    await drone.action.takeoff()
    
    # 稳稳爬升 12 秒稳住气流
    await asyncio.sleep(12)  

    print("🔄 [控制权移交]：正在切入 Offboard 模式...")
    await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
    
    try:
        await drone.offboard.start()
        print("🚀 Offboard 模式已死锁锁死！控制权成功交由 Python AI！")
    except OffboardError as error:
        print(f"❌ 切换 Offboard 失败: {error._result.result}，正在紧急降落...")
        await drone.action.land()
        return

    # 🎬 3D 双脑会师
    await perception_loop(drone)

    print("🛬 任务结束，正在自主降落...")
    try:
        await drone.offboard.stop()
    except Exception:
        pass
    await drone.action.land()
    print("🏁 飞机已安全着陆。")

if __name__ == "__main__":
    asyncio.run(main())