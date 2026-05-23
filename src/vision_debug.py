import cv2
import numpy as np

# 打开 Mac 本地摄像头
cap = cv2.VideoCapture(0)

print("🔍 纯视觉硬核诊断探针已启动...")
print("请把蓝色耳机放到镜头前，观察终端打印的 Area 数值和弹出的黑白窗口！")

while True:
    ret, frame = cap.read()
    if not ret:
        continue
    
    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    center_x, center_y = w // 2, h // 2
    
    # 🌟 极其宽容的自适应蓝色 HSV 捕获网
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # 🎯 纯蓝色物品的经典 HSV 过滤矩阵
    lower_blue = np.array([100, 100, 50])
    upper_blue = np.array([140, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    # 形态学滤波
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # 抓出画面里所有满足蓝色色块中，面积最大的那一个
        max_contour = max(contours, key=cv2.contourArea)
        current_area = cv2.contourArea(max_contour)
        
        # 📢 核心诊断打印：看看 OpenCV 究竟认为这个色块有多大
        print(f"实时状态: 抓到蓝色源 | 原始像素面积 (Area): {int(current_area)}")
        
        # 只要面积大于 100 像素就强行框起来
        if 100 < current_area < 80000:
            M = cv2.moments(max_contour)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                cv2.circle(frame, (cx, cy), 12, (0, 255, 0), -1)
                cv2.drawContours(frame, [max_contour], -1, (0, 255, 0), 2)
    else:
        print("实时状态: ❌ 画面中完全没有捕捉到任何满足 HSV 阈值的蓝色像素")

    # 弹出双视窗盲审
    cv2.imshow("LIVE_CAMERA (彩色)", frame)
    cv2.imshow("DIAGNOSIS_MASK (黑白)", mask)

    # 按 q 键退出
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()