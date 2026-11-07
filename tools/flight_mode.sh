#!/usr/bin/env bash
# flight_mode.sh — 起飞前关掉 WiFi/蓝牙，降落后恢复。
#
# 用法（在香橙派上跑）：
#   bash flight_mode.sh status   # 只看状态，不改任何东西
#   bash flight_mode.sh off      # 关 WiFi + 蓝牙（WiFi SSH 会断开，正常）
#   bash flight_mode.sh on       # 恢复 WiFi + 蓝牙
#
# 为什么要有这个：
#   板子 WiFi 是 2.4GHz，和 2.4GHz 遥控抢频段；飞行时不需要联网。
#   起飞前关掉，链路余量最大；降落后再开，方便取日志。
#
# 注意：
#   - `off` 会把当前 WiFi SSH 断掉，这是预期行为；最好在板子本地终端跑，
#     或者接受 SSH 断开、降落后再连。
#   - `on` 不能在“WiFi 已关”的 SSH 里跑（没网了）；要么本地终端，要么插网线
#     用 `ssh orangepi-lan` 跑。
#   - 只动 WiFi/蓝牙，不动飞控 UART、不动视觉程序。

set -u

MODE="${1:-status}"
WIFI_CONN="${WIFI_CONN:-helta的新路由}"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

temp_c() {
    local f
    f=$(ls /sys/class/thermal/thermal_zone0/temp 2>/dev/null | head -n1)
    if [ -n "$f" ]; then
        awk '{printf "%.1f", $1/1000}' "$f"
    else
        echo "n/a"
    fi
}

wifi_radio() {
    if have nmcli; then
        nmcli -t -f WIFI radio 2>/dev/null | head -n1
    else
        echo "nmcli-missing"
    fi
}

bt_powered() {
    if have bluetoothctl; then
        bluetoothctl show 2>/dev/null | awk -F': ' '/Powered/{print $2; exit}'
    else
        echo "bluetoothctl-missing"
    fi
}

wlan_ip() {
    ip -4 -brief addr show wlan0 2>/dev/null | awk '{print $3}' | head -n1
}

lan_ip() {
    ip -4 -brief addr show enP4p65s0 2>/dev/null | awk '{print $3}' | head -n1
}

status() {
    local wip lip
    wip=$(wlan_ip)
    lip=$(lan_ip)
    say "== radios =="
    say "wifi radio : $(wifi_radio)"
    say "bluetooth  : $(bt_powered)"
    say "wlan0      : ${wip:-down}"
    say "ethernet   : ${lip:-down}"
    say "== links =="
    if have nmcli; then
        nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null | grep -E '^(wlan0|enP4p65s0):' || true
    fi
    say "== system =="
    say "temp       : $(temp_c) C"
    say "uptime     : $(uptime -p 2>/dev/null || uptime)"
    say "npu        : $(cat /sys/kernel/debug/rknpu/version 2>/dev/null || echo 'n/a (root only)')"
}

turn_off() {
    say "[flight_mode] 先关蓝牙（避免 WiFi 断开时脚本被打断）..."
    if have bluetoothctl; then
        bluetoothctl power off >/dev/null 2>&1 && say "  bluetooth: off" || say "  bluetooth: off failed (ignored)"
    fi

    say "[flight_mode] 关 WiFi ..."
    if have nmcli; then
        nmcli radio wifi off 2>&1 || say "  nmcli radio wifi off failed"
    else
        say "  nmcli not found"
    fi
    sleep 1

    say "[flight_mode] WiFi/蓝牙已关。WiFi SSH 现在会断开。"
    status
}

turn_on() {
    say "[flight_mode] 恢复 WiFi/蓝牙 ..."
    if have nmcli; then
        nmcli radio wifi on 2>&1 || say "  nmcli radio wifi on failed"
    fi
    if have bluetoothctl; then
        bluetoothctl power on >/dev/null 2>&1 || true
    fi

    # 等自动连接；最多 20 秒
    local i wip
    for i in $(seq 1 20); do
        wip=$(wlan_ip)
        [ -n "$wip" ] && break
        sleep 1
    done

    if [ -z "$(wlan_ip)" ] && have nmcli; then
        say "[flight_mode] 自动连接没成功，手动激活 '$WIFI_CONN' ..."
        nmcli connection up "$WIFI_CONN" 2>&1 || true
        sleep 2
    fi

    status
}

case "$MODE" in
    off) turn_off ;;
    on) turn_on ;;
    status) status ;;
    *)
        say "用法: bash flight_mode.sh {off|on|status}"
        exit 2
        ;;
esac
