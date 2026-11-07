# 连接香橙派 5 Pro（SSH 免密）

> 适用：板子已经开机、和 Windows 在同一个路由器下（有线或 WiFi 都行）。
> 目标：**不用显示器、不用键盘**，在 Windows 上直接操作板子。
>
> 板子的 IP、账号、镜像版本等环境事实见 `docs/ENV.md` 的 C 节。

---

## 一、已经配好了什么

2026-11-07 已配置：

- Windows 上生成了专用密钥：`~/.ssh/orangepi5pro_ed25519`（私钥，别外传）
- 公钥已写入板子的 `~/.ssh/authorized_keys`
- Windows 的 `~/.ssh/config` 加了别名 `orangepi`
- 桌面放了快捷方式：`连接香橙派.bat`
- 板子 WiFi 已连上 `helta的新路由`，设为开机自动连接；**不插网线也能 SSH**

所以现在登录**不需要输密码**。

---

## 二、怎么连（两种方式，选一个）

### 方式 1：双击桌面图标（最简单）

双击 **`连接香橙派.bat`**，会弹出一个黑色窗口，直接就是板子的终端。

### 方式 2：PowerShell

按 `Win + R` → 输入 `powershell` → 回车，然后：

```powershell
ssh orangepi
```

第一次连某个地址会问：

```text
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

输入 `yes` 回车。以后不会再问。

> `ssh orangepi` 现在走 **WiFi**（`192.168.100.151`）。如果插着网线、想走有线，
> 用 `ssh orangepi-lan`（`192.168.100.147`）。

进去后提示符长这样：

```text
orangepi@orangepi5pro:~$
```

看到它，就说明你已经在板子里了。

---

## 三、免密登录和“密码”是什么关系

- **免密登录用的是密钥，不需要密码。** 私钥在 Windows，公钥在板子，配对成功就放行。
- **账号本身仍然有密码**，主要给 `sudo`（管理员权限）用。
- 默认密码是 `orangepi`，**建议改掉**。改密码**不会影响** `ssh orangepi`。

### 改密码（在板子的 SSH 里执行）

```bash
passwd
```

按提示：

1. 先输**当前密码**（默认 `orangepi`，输入时不显示，正常）
2. 再输**两遍新密码**

改完记牢。忘了密码的话，密钥还能登录，但 `sudo` 会卡住，处理起来很麻烦。

> 不建议把密码设成 `123456`、生日之类；板子接在路由器上，局域网里其他人也能访问。

---

## 四、进去以后怎么用（最常用）

| 你想干什么 | 命令 | 说明 |
| --- | --- | --- |
| 看当前目录有什么 | `ls` | 类似资源管理器 |
| 进某个目录 | `cd 目录名` | `cd ..` 回上一级 |
| 看自己在哪 | `pwd` | 打印当前路径 |
| 看文件内容 | `cat 文件名` | 文本文件 |
| 用管理员权限执行 | `sudo 命令` | 会要密码 |
| 看 IP | `hostname -I` | |
| 看温度 | `cat /sys/class/thermal/thermal_zone0/temp` | 除以 1000 是摄氏度 |
| 看磁盘 | `df -h` | |
| 看内存 | `free -h` | |
| 退出 SSH（板子继续跑） | `exit` | |
| 重启板子 | `sudo reboot` | |
| 关机 | `sudo shutdown -h now` | 等灯灭再断电 |

### 关机流程（重要）

```bash
sudo shutdown -h now
```

等板子的灯灭、风扇停，**再拔电源**。直接拔电源可能把 SD 卡文件系统弄坏。

---

## 五、在 Windows 和板子之间传文件

在 **Windows 的 PowerShell** 里（不是板子里）执行：

```powershell
# Windows -> 板子（放到板子的家目录）
scp .\某个文件.txt orangepi:~/

# 板子 -> Windows（拉到当前目录）
scp orangepi:~/某个文件.txt .
```

整个文件夹加 `-r`：

```powershell
scp -r .\vnav orangepi:~/
```

---

## 六、现在可以把显示器拔了

SSH 通了以后，板子可以**完全无头运行**：

- 拔掉 HDMI、键盘、鼠标，板子照常跑；
- **网线也可以拔**：WiFi 已配好，`ssh orangepi` 会自动走 WiFi；
- 如果 WiFi 出问题，插回网线用 `ssh orangepi-lan`；
- 下次开机也不用接显示器，等 1–2 分钟，Windows 上 `ssh orangepi` 即可；
- 如果哪天需要图形界面，再插回显示器，或者以后装 VNC / xrdp。

---

## 七、如果 `ssh orangepi` 连不上

按顺序排查：

1. **板子开机了吗？** 等 1–2 分钟。
2. **在同一个路由器下吗？** Windows 和板子都要连 `192.168.100.x` 这个网。
3. **IP 变了吗？** 板子是有线 DHCP，路由器重启后可能换 IP。见下一节。
4. **网线松了吗？** 看板子网口灯。
5. 还不行就在 Windows 上：

```powershell
ping 192.168.100.151   # WiFi
ping 192.168.100.147   # 有线（如果插着网线）
```

不通就是网络问题，不是 SSH 问题。

---

## 八、防止 IP 变来变去（建议做一次）

板子两条链路都是 DHCP，**IP 不保证永远不变**。同一台设备通常会拿到同一个地址，但路由器重启、租约到期、地址池调整都可能换。

最省事的办法是在**路由器后台**做 **DHCP 静态绑定**，两条都做最好：

| 链路 | MAC | 固定 IP |
| --- | --- | --- |
| WiFi `wlan0` | `8c:cd:fe:10:a0:34` | `192.168.100.151` |
| 有线 `enP4p65s0` | `c0:74:2b:f8:cf:6f` | `192.168.100.147` |

- 路由器地址：`192.168.100.1`（浏览器打开，用管理员账号登录）
- 不同路由器叫法不同：**DHCP 静态分配 / 地址保留 / IP 绑定 / MAC 绑定**

> 绑 **WiFi 那条**就够了（`ssh orangepi` 走它）；有线想插的时候再绑。
> 绑定后重启板子或重新连 WiFi 生效。

**如果哪天 IP 真变了怎么找：**

```powershell
arp -a | findstr 8c-cd-fe
```

会显示类似 `192.168.100.xxx  8c-cd-fe-10-a0-34`，那个就是新的 WiFi IP。
也可以进路由器后台看“已连接设备”。

---

## 九、常见问题

| 现象 | 原因 | 怎么办 |
| --- | --- | --- |
| `ssh: connect to host ... port 22: Connection refused` | 板子没开机 / SSH 没起来 | 等一会儿；插显示器看；重启板子 |
| `Permission denied (publickey)` | 密钥没装上 / 用了错的文件 | 在 Windows 上 `ssh -i ~/.ssh/orangepi5pro_ed25519 orangepi@IP` 试 |
| `Connection timed out` | IP 变了 / 不在同一网 | `ping` 一下，路由器后台看设备列表 |
| 输入 `sudo` 后密码不对 | 改过密码忘了 | 用密钥还能进，但需要重置密码（麻烦，尽量记牢） |
| 桌面弹 `pasystray has stopped` | 音频托盘小程序崩了 | 点 Don't send / 关掉，不影响使用 |

---

## 十、下一步

SSH 稳定后，就可以在板子上装依赖、跑 RKNN 了：

- 先验 NPU：`cat /sys/kernel/debug/rknpu/version`（当前是 v0.9.6）
- 再按 `docs/ORANGEPI_BRINGUP.md` 阶段 1 转模型
- 相机到了再按阶段 3 标定

**在板子上不要装 `rknn-toolkit2`**（那是 x86 转换用的），只装 `rknn-toolkit-lite2`。
