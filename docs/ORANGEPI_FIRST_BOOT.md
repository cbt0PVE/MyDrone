# 香橙派 5 Pro · 零基础开箱到能 SSH

> 给第一次用开发板的人。**今天只做三件事：写 SD 卡 → 开机进桌面 → 连上网。**
> 不要一上来装 RKNN、不要接飞控。先把板子当一台小电脑用起来。
>
> 技术版的分阶段验收见 `docs/ORANGEPI_BRINGUP.md`，这份是"手把手"版。

---

## 零、先确认你手上有这些

| 东西 | 要求 | 没有会怎样 |
| --- | --- | --- |
| microSD 卡 | **32GB 以上**，Class 10 / A2，正经品牌 | 杂牌/扩容卡会写坏、启动一半死机 |
| 读卡器 | USB 读卡器或笔记本自带 SD 口 | 没法写卡 |
| 电源 | **5V/5A**，USB-C 口 | 手机充电头（5V/2A）能亮但一跑就重启 |
| HDMI 线 + 显示器 | 电视也行 | 没有就只能用串口，见第八节 |
| USB 键盘 + 鼠标 | 普通有线/无线都行 | 进不了桌面 |
| 散热片 + 风扇 | 铝片就行，最好带风扇 | 跑几分钟就降频，甚至烫手 |
| 网线（推荐） | 接路由器 | 用 WiFi 也行，但 2.4G 以后会干扰遥控 |

> **写卡会清空 SD 卡里的所有东西**。先确认卡里没有你要留的照片/文件。

---

## 一、下载系统镜像

1. 打开香橙派官网，进 **Orange Pi 5 Pro** 的产品页 → **下载 / Downloads**。
2. 选 **Ubuntu 22.04**（桌面版 Desktop 最好，带图形界面；Server 版没有桌面）。
3. 文件名里应该同时出现 **`5pro`** 和 **`ubuntu`/`jammy`**。
   **千万别下成 Orange Pi 5 / 5B 的镜像**——型号不对，开不了机。
4. 下载下来通常是：
   - `.img.xz`：可以直接写，不用解压；
   - `.7z` / `.tar.gz`：先用 **7-Zip** 解压，里面那个 `.img` 才是要写的文件。
5. 文件很大（1–2GB），下载慢是正常的。

> 2026-11-07 实测：`..._linux6.1.43.7z` 在 Google Drive 上被限流
> （"Too many users have viewed or downloaded"），`..._linux5.10.160.7z` 可以正常下。
> 两版都是 Ubuntu 22.04 桌面版，先用 5.10.160；NPU 驱动两者都带，后面真有问题再换。

> 官网的 Google Drive 链接打不开时，换百度网盘链接，或者找国内镜像。
> 不要从"XX系统之家"之类的地方下，镜像可能被改过。

---

## 二、把镜像写到 SD 卡（Windows）

用 **balenaEtcher**，最简单，不会写错模式。

1. 浏览器搜 **balenaEtcher**，进官网下载 Windows 版，安装。
2. 把 microSD 卡插进读卡器，再插电脑。
3. 打开 Etcher：
   - **Flash from file** → 选你下载的 `.img` 或 `.img.xz`；
   - **Select target** → 选那张 SD 卡（**看清楚容量，别选成你的移动硬盘/U 盘**）；
   - **Flash!** → 等进度条走完。
4. 写完如果 Windows 弹窗说「**需要格式化磁盘**」——**点取消**。
   这是 Linux 分区，Windows 不认识，格式化就把系统毁了。
5. 点 Etcher 里的 **Safely eject**，或者右下角安全弹出，再把卡拔下来。

### 常见错误

- 用 Rufus 选了「ISO 模式」→ 写出来不能启动。用 Etcher 最稳；非要用 Rufus 就选 **DD 模式**。
- 卡是 64GB 以上、Windows 提示格式不对 → 不用管，Etcher 会直接覆盖。
- 写到一半失败 → 换读卡器或换卡，别反复重试同一张杂牌卡。

### 备选：Rufus 便携版（不想装 Etcher 时）

1. 下载 **rufus-4.15p.exe**（便携版，约 2MB，免安装）。
2. 右键 → **以管理员身份运行**（写盘需要管理员权限）。
3. **设备**选那张 32GB 卡；
4. **引导类型选择** → 点「选择」→ 选解压出来的 `.img`；
5. 如果弹出 `ISOHybrid image detected` → 选 **Write in DD Image mode**；
6. 点 **START** → 确认会清空磁盘 → 等进度条走完。

> Rufus 默认会隐藏系统盘，但还是要**看一眼容量**：选中的应该是 29–31GB 的
> `Mass Storage Device`，不是你的 C/D 盘。

---

## 三、第一次开机

1. **先装散热片/风扇**，再通电。RK3588S 很热。
2. 把 SD 卡插进板子的 microSD 槽，**插到底会"咔"一声**。
3. 接好：
   - HDMI 线 → 显示器/电视；
   - USB 键盘、鼠标；
   - 网线（推荐，插路由器 LAN 口）；
   - **最后**接电源。
4. 第一次开机要 **1–3 分钟**，屏幕可能黑一会儿，**不要反复断电**。
   有的镜像会自动重启一次，正常。
5. 出现登录界面：
   - 老镜像默认账号 **`orangepi`**，密码 **`orangepi`**；
   - 新镜像第一次开机会让你**设置新密码**，按提示设一个你记得住的（别用中文、别用空格）。
6. 进桌面后，先别急着干别的，看右上角有没有网络图标。

> 如果插电后灯亮但一直黑屏：先换一根 HDMI 线/换一个显示器接口，再检查 SD 卡是不是插反/没插到底。

---

## 四、连上网

### 有网线（推荐）

插上就能上网。跳过这节，直接看第五节。

### 用 WiFi

1. 点桌面右上角的网络图标 → 选你的 WiFi → 输入密码。
2. 没有桌面（Server 版）时，在终端里：

```bash
nmcli device wifi list
nmcli device wifi connect "你的WiFi名字" password "你的WiFi密码"
```

> 建议连 **5GHz**。以后板子装到飞机上，2.4GHz WiFi 可能干扰遥控接收机。

---

## 五、打开 SSH（这样就能在 Windows 上操作板子）

在板子上打开终端（桌面按 `Ctrl + Alt + T`），依次输入：

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
hostname -I
```

- 第一条会要你输密码（输入时屏幕不显示，正常，输完回车）。
- 最后一条会打印板子的 IP，形如 `192.168.1.23`。
- 把 **IP 记下来**。

### 在 Windows 上连过去

1. 按 `Win + R`，输入 `powershell`，回车。
2. 输入（把 IP 换成你记下的）：

```powershell
ssh orangepi@192.168.1.23
```

3. 第一次会问 `Are you sure you want to continue connecting?` → 输入 `yes` 回车。
4. 输入密码（同样不显示），进去后提示符会变成 `orangepi@orangepi5pro:~$`。

> Windows 10/11 自带 SSH。如果提示 `ssh 不是内部或外部命令`：
> 设置 → 应用 → 可选功能 → 添加功能 → 安装 **OpenSSH 客户端**。

---

## 六、确认板子是健康的

SSH 进去后，逐条跑，看输出：

```bash
# 1. 系统信息
uname -a
cat /etc/os-release

# 2. NPU 驱动（最重要，读不到就先别往下走）
dmesg | grep -i rknpu
cat /sys/kernel/debug/rknpu/version
ls /dev/rknpu*

# 3. 温度（单位是毫摄氏度，45000 = 45°C）
cat /sys/class/thermal/thermal_zone*/temp

# 4. 存储和内存
df -h
free -h
lsblk

# 5. 摄像头（如果已经插了 USB 摄像头）
ls /dev/video*
```

**正常的样子：**

- `rknpu` 那几条能看到版本号或驱动加载信息；
- 温度在 40–60°C 之间（空载）；
- `df -h` 里根分区有几十 GB 可用；
- 插了 USB 摄像头会出现 `/dev/video0`。

**不正常的样子：**

- `dmesg | grep rknpu` 什么都没有 → 镜像/内核不对，换官方 5 Pro 镜像重来；
- 温度 80°C 以上 → 散热没装好，先处理散热；
- `df -h` 根分区只有几个 GB → SD 卡没自动扩容，告诉我，我给你扩。

---

## 七、关机

**不要直接拔电源。** 在终端里：

```bash
sudo shutdown -h now
```

等板子灯灭、风扇停，再断电。直接拔电源可能把 SD 卡文件系统弄坏。

---

## 八、没有显示器怎么办（备选）

不推荐第一次就这么干，但确实可以：

1. 买一个 **USB 转 TTL 串口模块（3.3V 电平）**；
2. 接板子的 UART 调试口：**TX 接 RX、RX 接 TX、GND 接 GND**（**不要接 5V**）；
3. 电脑上用 **PuTTY**，波特率 **115200**；
4. 能看到启动日志，登录后同样跑第五节的命令。

接线错了可能烧板子，没把握就先借个显示器。

---

## 九、今天做完，你应该得到

- [ ] 板子能进桌面
- [ ] Windows 能 `ssh orangepi@<IP>` 登录
- [ ] `rknpu` 版本能看到
- [ ] 温度正常（<60°C 空载）
- [ ] SD 卡剩余空间 >20GB

这五条都过了，再去 `docs/ORANGEPI_BRINGUP.md` 做 RKNN 和接飞控。
**一条没过就不要往下走**，后面所有问题都会变得更难查。

---

## 十、常见问题速查

| 现象 | 原因 | 怎么办 |
| --- | --- | --- |
| 通电灯亮、屏幕黑 | HDMI/显示器/卡没插好 | 换线、换屏、重插卡 |
| 一直卡在开机 logo | 镜像下错型号 / 卡写坏 | 重下 5 Pro 镜像、重写卡 |
| 开机后反复重启 | 电源不够（5V/2A） | 换 5V/5A 电源和粗线 |
| 很烫、风扇转但卡 | 散热不够 / 降频 | 加散热片风扇，别放床上 |
| `ssh: connection refused` | SSH 没开 / IP 变了 | 板子上 `sudo systemctl status ssh`，重新 `hostname -I` |
| `apt update` 报错 | 网络/DNS/源的问题 | 先 `ping baidu.com`，不通就是网没连上 |
| Windows 提示格式化 SD | 正常现象 | **点取消**，千万别格式化 |
