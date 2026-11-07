# 起飞前点选目标（enroll_server）

> 用途：多人开局时，**人来点选**实验人员；锁定后才建 gallery，之后短时遮挡自动重捕获。
> 不依赖互联网，板子本地网页即可。

---

## 一、流程

```text
板子启动（家里 WiFi 或 OrangePi-Enroll 热点）
→ 启动点选网页
→ 手机/PC 浏览器打开
→ 画面里拖框框住实验人员
→ 保存 target.json
→ 关闭网页服务
→ 启动 run_tracking.py --target
```

**点选是起飞前动作，不是飞起来再点。**

---

## 二、启动点选服务

板子上：

```bash
# USB 相机
python3 tools/enroll_server.py --source 0 --out ~/target.json --port 8000

# 没有相机时用视频测试
python3 tools/enroll_server.py --source ~/person_pan.avi --out ~/target.json --port 8000
```

打开：

- 家里 WiFi：`http://192.168.100.151:8000`
- 板子热点：`http://10.42.0.1:8000`

页面上：

1. 在画面里**按住拖动**，框住实验人员；
2. 松手自动保存；
3. 状态显示 `已锁定：0.2, 0.2, 0.5, 0.8`；
4. 点“关闭服务”，或 SSH 里 `Ctrl+C`。

保存内容：

```json
{
  "bbox_norm": [0.2, 0.2, 0.5, 0.8],
  "frame_width": 640,
  "frame_height": 480,
  "created": "2026-11-08 00:25:52"
}
```

> bbox 是**归一化坐标**，和分辨率无关。

---

## 三、启动跟踪

```bash
# 纯视觉验证
bash ~/run_with_rknn.sh python3 run_tracking.py \
    --camera 0 --weights ~/best_heads.rknn \
    --target ~/target.json --mot --no-arm

# 实飞（去掉 --no-arm；先拆桨/系留验证）
bash ~/run_with_rknn.sh python3 run_tracking.py \
    --camera 0 --weights ~/best_heads.rknn \
    --target ~/target.json --mot
```

行为：

- 首帧把 `bbox_norm` 转成像素，调用 `TrackingDetector.lock_target()`；
- 锁定 `id=1`，开始积累外观 gallery；
- 之后短时遮挡/走几步，按 gallery 重捕获；
- 丢失超过 `target_release_s` → 悬停/交还人工，不自动换人。

---

## 四、网络

- 实验室：板子和手机/PC 连同一个路由器（不需要互联网）；
- 野外：板子开热点 `OrangePi-Enroll`，密码 `12345678`，IP `10.42.0.1`；
- 电脑 SSH：
  ```bash
  ssh -i C:\Users\<你>\.ssh\orangepi5pro_ed25519 orangepi@10.42.0.1
  ```
- 小米/Android 热点可能隔离客户端，**不要用手机热点做板子↔PC 局域网**；用板子 AP 或路由器。

---

## 五、注意

1. **摄像头不能被两个进程同时占**：点选服务关掉后再启动跟踪。
2. 首帧必须能看到实验人员；看不到就重新点选。
3. 网页没有鉴权，只在可信局域网使用，用完关掉。
4. 多人同色时，点选就是最终裁决；不要让它自动猜。
5. gallery 从无人机画面自动积累，**不要用手机照片直接当 gallery**（域差太大）。
