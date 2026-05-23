import asyncio
import cv2
import numpy as np
from mavsdk import System
# 💡 核心对齐：新版 MAVSDK 正确的 Offboard 速度控制类导入路径
from mavsdk.offboard import VelocityNedYaw, OffboardError

# 📐 全局变量：用于保存上一次的横向误差，计算 PD 控制律的微分项（D）
global last_error_x
last_error_x = 0

async def perception_loop(drone):
    """ 👁️ 二维视觉感知 + 🚀 左右横移(Y轴)PD 闭环控制外环 """
    global last_error_x
    
    # 📐 核心 PD 控制律参数（仅针对左右平移）
    Kp_y = 0.004   # 比例系数：把像素误差放大/缩小为物理速度
    Kd_y = 0.001   # 微分系数：阻尼项，用来抑制飞机左右平移时的惯性超调

    # 打开 Mac 本地摄像头
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 感知错误: 无法打开 Mac 摄像头")
        return

    print("🎯 [基础二维追踪外环激活]：正在执行左右平移伺服锁定...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.01)
            continue
        
        # 画面镜像翻转，使飞机的平移方向与镜子里的你左右感官对齐
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        center_x = w // 2  # 画面横向中心点像素坐标
        
        # 1. BGR 转 HSV 颜色空间，提取黄色鸭舌帽
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_yellow = np.array([11, 43, 46])
        upper_yellow = np.array([34, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        # 2. 数学形态学开运算去噪（消除背景小黄点干扰）
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # 3. 提取轮廓并利用几何矩解算帽子质心
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 默认情况下，控制向量全部清零（原地悬停）
        out_vx = 0.0
        out_vy = 0.0
        out_vz = 0.0
        out_yaw = 0.0
        
        if contours:
            max_contour = max(contours, key=cv2.contourArea)
            current_area = cv2.contourArea(max_contour)
            
            # 过滤面积小于 800 像素的噪点
            if current_area > 800: 
                M = cv2.moments(max_contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    # 🎯 解算横向像素误差：帽子中心离画面中心的距离
                    error_x = cx - center_x          
                    
                    # 📐 [核心算法] 增量式 PD 控制律解算
                    deriv_y = error_x - last_error_x
                    out_vy = Kp_y * error_x + Kd_y * deriv_y
                    last_error_x = error_x  # 滚动保存误差
                    
                    # 绘制视觉追踪反馈十字靶心
                    cv2.circle(frame, (cx, cy), 12, (0, 0, 255), -1)
                    cv2.putText(frame, f"LOCK | ex: {error_x}", (cx+15, cy), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # 绘制画面正中央的白色物理十字参考线
        cv2.line(frame, (center_x, h // 2 - 20), (center_x, h // 2 + 20), (255, 255, 255), 1)
        cv2.imshow("MyDrone AI - 2D Unified Tracker", frame)

        # 🛡️ 工业级安全级饱和截断（限制最大横移速度为 1.2 m/s，防止暴走）
        out_vy = max(-1.2, min(1.2, out_vy))

        # 🚀 注入 PX4 速度位置环
        # 注意：此处只有 out_vy 随着帽子在变，vx、vz、yaw 全被锁死在 0
        try:
            await drone.offboard.set_velocity_ned(
                VelocityNedYaw(out_vx, out_vy, out_vz, out_yaw)
            )
        except Exception as e:
            pass

        # 按 'q' 键优雅退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
        # 挂起 10ms，维持 100Hz 外环刷新率并释放系统套接字
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

    # 初始化 Offboard 模式，先高频灌入零速度占位包
    await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))

    print("🔌 [越塔模式] 正在直接解锁电机...")
    await drone.action.arm()

    print("🛫 自动起飞至 2.5 米安全悬停高度...")
    await drone.action.takeoff()
    
    # 稳稳爬升 12 秒让底层 EKF2 定位完全对齐
    await asyncio.sleep(12)  

    print("🔄 [控制权移交]：正在切入 Offboard 模式...")
    try:
        await drone.offboard.start()
        print("🚀 Offboard 模式已成功锁死！控制权移交 Python AI！")
    except OffboardError as error:
        print(f"❌ 切换 Offboard 失败: {error._result.result}，正在紧急降落...")
        await drone.action.land()
        return

    # 🎬 视觉伺服外环接管
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