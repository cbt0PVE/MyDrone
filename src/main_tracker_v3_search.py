import asyncio
import cv2
import numpy as np
from mavsdk import System
from mavsdk.offboard import VelocityNedYaw, OffboardError

global last_error_x
last_error_x = 0

async def perception_loop(drone):
    """ 👁️ 三维视觉感知 + 🧠 智能自适应检索状态机外环（圆度几何锁强固版） """
    global last_error_x
    
    last_error_x = 0
    last_error_y = 0
    
    # 📐 PID 控制率矩阵
    Kp_y = 0.004   
    Kd_y = 0.001   
    Kp_x = 0.0005  
    Kp_z = 0.003   
    Kd_z = 0.0008  

    current_state = "TRACKING"    
    loss_counter = 0              
    search_yaw_speed = 15.0       
    last_known_direction = 1.0    

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 感知错误: 无法打开 Mac 摄像头")
        return

    TARGET_AREA = 12000 
    print("🎯 [V3 圆度控制版外环激活]：正在铁血清退方形干扰，锁死圆形鸭舌帽...")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.01)
            continue
        
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        center_x, center_y = w // 2, h // 2
        
        # 🟡 经典黄色 HSV 切片
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower_yellow = np.array([11, 43, 46])
        upper_yellow = np.array([34, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        target_detected = False
        error_x = 0
        error_y = 0
        error_area = 0
        
        valid_targets = []
        
        if contours:
            for cnt in contours:
                area = cv2.contourArea(cnt)
                
                # 1. 🔍 面积截断门：上限扩大到 18 万，允许大帽子近距离怼镜头
                if 400 < area < 180000:
                    # 计算轮廓周长
                    perimeter = cv2.arcLength(cnt, True)
                    
                    if perimeter > 0:
                        # 2. 📐 计算核心圆度 (Circularity)
                        circularity = (4 * np.pi * area) / (perimeter ** 2)
                        
                        # 3. 🛡️ 圆度安全锁：强行过滤掉周长极长的方形床架、横梁等低圆度干扰项
                        # 只有圆度在 0.3 到 0.9 之间的规则圆润物体才能通关！
                        if 0.3 < circularity < 0.9:
                            x, y, box_w, box_h = cv2.boundingRect(cnt)
                            aspect_ratio = float(box_w) / box_h
                            
                            if 0.6 < aspect_ratio < 2.2:
                                valid_targets.append((cnt, area, circularity))
            
            # 筛选通关群体中面积最大的优胜者
            if valid_targets:
                max_target = max(valid_targets, key=lambda item: item[1])
                best_contour = max_target[0]
                current_area = max_target[1]
                best_circularity = max_target[2]
                
                M = cv2.moments(best_contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    
                    error_x = cx - center_x          
                    error_y = cy - center_y          
                    error_area = TARGET_AREA - current_area  
                    
                    target_detected = True
                    loss_counter = 0  
                    last_known_direction = 1.0 if error_x > 0 else -1.0
                    
                    # 动态追踪 UI 渲染
                    cv2.drawContours(frame, [best_contour], -1, (0, 255, 0), 2) 
                    cv2.circle(frame, (cx, cy), 8, (0, 255, 0), -1)
                    cv2.putText(frame, f"BALL LOCK | Circ: {round(best_circularity, 2)}", (cx+15, cy), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        # 🧠 状态机决策链
        if target_detected:
            current_state = "TRACKING"
        else:
            loss_counter += 1
            if loss_counter > 15:
                current_state = "SEARCHING"

        # 辅助渲染
        cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (255, 255, 255), 1)
        cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (255, 255, 255), 1)
        status_color = (0, 255, 0) if current_state == "TRACKING" else (0, 0, 255)
        cv2.putText(frame, f"STATE: {current_state}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)
        
        cv2.imshow("MyDrone AI - V3 FSM Tracker", frame)
        cv2.imshow("DIAGNOSIS - Mask Window", mask)

        # 📐 控制律执行层分支
        if current_state == "TRACKING":
            deriv_y = error_x - last_error_x
            out_vy = Kp_y * error_x + Kd_y * deriv_y
            last_error_x = error_x
            
            out_vx = Kp_x * error_area
            
            deriv_z = error_y - last_error_y
            out_vz = Kp_z * error_y + Kd_z * deriv_z
            last_error_y = error_y
            
            out_yaw = 0.005 * error_x 

        elif current_state == "SEARCHING":
            out_vx, out_vy, out_vz = 0.0, 0.0, 0.0
            out_yaw = search_yaw_speed * last_known_direction
            last_error_x = 0
            last_error_y = 0

        # 安全饱和限速
        out_vx = max(-1.0, min(1.0, out_vx))
        out_vy = max(-1.2, min(1.2, out_vy))
        out_vz = max(-0.8, min(0.8, out_vz)) 
        out_yaw = max(-25.0, min(25.0, out_yaw)) 

        try:
            await drone.offboard.set_velocity_ned(
                VelocityNedYaw(out_vx, out_vy, out_vz, out_yaw)
            )
        except Exception as e:
            print(f"⚠️ 飞控指令注入突发中断: {e}")

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
        await asyncio.sleep(0.01)

    cap.release()
    cv2.destroyAllWindows()

async def main():
    drone = System()
    print("📡 正在呼叫 PX4 虚拟飞控...")
    await drone.connect(system_address="udp://:14540")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✅ 通信网络套接字打通！")
            break

    print("🔌 正在直接解锁电机...")
    await drone.action.arm()

    print("🛫 自动起飞至 2 米安全悬停高度...")
    await drone.action.takeoff()
    
    await asyncio.sleep(12)  

    print("✨ 正在连续灌入预设速度流以对齐飞控安全死锁机制...")
    for _ in range(10):
        await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
        await asyncio.sleep(0.1)

    print("🔄 正在切入 Offboard 模式...")
    try:
        await drone.offboard.start()
        print("🚀 控制权成功交由 Python V3 状态机！")
    except OffboardError as error:
        print(f"❌ 切换失败，紧急降落: {error._result.result}")
        await drone.action.land()
        return

    await perception_loop(drone)

    print("🛬 任务结束，自主降落...")
    try:
        await drone.offboard.stop()
    except Exception:
        pass
    await drone.action.land()

if __name__ == "__main__":
    asyncio.run(main())