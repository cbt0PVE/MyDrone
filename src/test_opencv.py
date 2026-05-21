import cv2
import numpy as np

def nothing(x):
    pass

def main():
    # 1. 初始化 Mac 的原生摄像头（通常 0 是内置 Camera）
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Error: 无法打开 Mac 摄像头，请检查系统隐私权限设置。")
        return

    # 2. 创建一个专门用来高频调参的窗口
    window_name = "Target Perception Tuner"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 400, 350)

    # 3. 创建 HSV 颜色空间的上下限滑动条 (初始值默认设为一种常见的绿色范围)
    cv2.createTrackbar("Min H", window_name, 35, 179, nothing)
    cv2.createTrackbar("Max H", window_name, 85, 179, nothing)
    cv2.createTrackbar("Min S", window_name, 43, 255, nothing)
    cv2.createTrackbar("Max S", window_name, 255, 255, nothing)
    cv2.createTrackbar("Min V", window_name, 46, 255, nothing)
    cv2.createTrackbar("Max V", window_name, 255, 255, nothing)

    print("🚀 感知端调试就绪！请在画面前放置你的纯色目标（如红可乐罐/绿杯子）...")
    print("💡 提示：调整滑动条，直到右侧 Mask 画面中只有你的目标呈现纯白色，背景全黑。按 'q' 退出。")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Error: 无法获取图像帧")
            break

        # 镜像翻转画面，符合人类直觉
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        # 4. 色彩空间转换：BGR -> HSV (飞控视觉追踪标配，对光照最鲁棒)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 5. 实时读取滑块上的数值
        min_h = cv2.getTrackbarPos("Min H", window_name)
        max_h = cv2.getTrackbarPos("Max H", window_name)
        min_s = cv2.getTrackbarPos("Min S", window_name)
        max_s = cv2.getTrackbarPos("Max S", window_name)
        min_v = cv2.getTrackbarPos("Min V", window_name)
        max_v = cv2.getTrackbarPos("Max V", window_name)

        lower_color = np.array([min_h, min_s, min_v])
        upper_color = np.array([max_h, max_s, max_v])

        # 6. 二值化掩膜操作：过滤颜色
        mask = cv2.inRange(hsv, lower_color, upper_color)

        # 7. 核心算法攻坚：形态学滤波（消除斑点噪声）
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)  # 开运算：消噪点
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel) # 闭运算：填孔洞

        # 8. 核心算法攻坚：几何矩解算（计算目标质心坐标）
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            # 找到面积最大的轮廓（防止背景有微小同色干扰）
            max_contour = max(contours, key=cv2.contourArea)
            
            if cv2.contourArea(max_contour) > 500: # 过滤过小的伪目标
                # 计算轮廓的矩
                M = cv2.moments(max_contour)
                if M["m00"] != 0:
                    # 🎯 算出了目标在图像中的绝对像素坐标 (xt, yt)
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])

                    # 📐 计算相对图像中心的像素误差 (ex, ey) —— 这将是未来发给飞控的控制源！
                    error_x = cx - (w // 2)
                    error_y = (h // 2) - cy  # 图像坐标系 Y 轴向下，取反使上方为正

                    # 在原图上绘制追踪靶心和坐标提示
                    cv2.circle(frame, (cx, cy), 10, (0, 0, 255), -1)
                    cv2.line(frame, (w // 2, h // 2), (cx, cy), (255, 0, 0), 2)
                    
                    cv2.putText(frame, f"Tracking Target", (cx + 15, cy - 15), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    cv2.putText(frame, f"Error X: {error_x}px, Y: {error_y}px", (20, 40), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # 绘制画面中心十字参考线
        cv2.line(frame, (w // 2 - 20, h // 2), (w // 2 + 20, h // 2), (255, 255, 255), 2)
        cv2.line(frame, (w // 2, h // 2 - 20), (w // 2, h // 2 + 20), (255, 255, 255), 2)

        # 9. 画面双联拼接显示
        mask_3ch = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        display_img = np.hstack((frame, mask_3ch))

        cv2.imshow("MyDrone AI - Perception Loop", display_img)

        # 按 'q' 键安全退出
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
