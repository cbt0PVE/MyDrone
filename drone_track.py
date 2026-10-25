from ultralytics import YOLO

def main():
    # 1. 加载轻量版模型（第一次运行会自动下载官方的 yolov8n.pt 权重）
    model = YOLO("yolov8n.pt") 

    # 2. 指定检测源：0 代表电脑自带摄像头。
    # 如果你想测试无人机视频，可以把视频丢进同目录下，这里改成 "video.mp4"
    source = "drone_test.mp4"

    print("🚀 正在启动 Windows 本地 RTX 4060 实时画面追踪...")
    print("💡 提示：运行后会弹出摄像头窗口。在窗口内按下键盘上的 'q' 键可以退出。")
    
    # 3. 执行多目标跟踪
    model.track(
        source=source,
        conf=0.3,             # 置信度：低于 0.3 的目标会被过滤
        iou=0.5,              # 密集人群遮挡时防止错乱的阈值
        tracker="bytetrack.yaml",  # 顶级多目标跟踪算法
        classes=[0],          # 🎯 0 代表 'person'，只检测和跟踪人
        show=True,            # ✨ 本地专属：直接在屏幕上弹出实时渲染的追踪画面！
        save=True             # 录制一份保存下来
    )

if __name__ == "__main__":
    main()
