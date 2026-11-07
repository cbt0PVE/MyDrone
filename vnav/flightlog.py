# -*- coding: utf-8 -*-
"""飞行日志：人看的文本 + 机器分析的 JSONL，双写。

设计目标
--------
1. **格式稳定**：每行都是 `[级别][HH:MM:SS.mmm](消息 字段=值 ...)`，
   既好读又方便 grep / awk / pandas 解析。
2. **不拖慢控制**：状态行默认 2Hz；事件（解锁/切换/丢目标/降落）立即写。
   20Hz 全量写盘没有必要，还会让日志淹没在噪声里。
3. **线程安全**：视觉线程、控制协程、状态任务可能同时写，内部一把锁。
4. **双格式**：
   - `.log`  —— 人看的，和终端输出一致；
   - `.jsonl` —— 每行一个 JSON，字段保留原始数值，方便画曲线。
5. **无第三方依赖**：只用标准库，香橙派上直接跑。

用法
----
    from vnav.flightlog import FlightLogger

    fl = FlightLogger(log_dir="logs", prefix="track", state_hz=2.0)
    fl.log("link_connected", port="serial://COM5:57600")
    fl.event("armed", level="INFO")
    fl.state(mode="OFFBOARD", armed=1, alt=1.02, att=(0.4, -0.2, 87.3))
    fl.close()

文本行示例：

    [INFO][18:36:43.123](link_connected port=serial://COM5:57600)
    [STATE][18:36:43.623](mode=OFFBOARD armed=1 alt=1.02 alt_src=laser ...)
    [WARN][18:36:44.001](safety_hold reason=target_lost age=0.62)
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

__all__ = ["FlightLogger", "fmt", "read_cpu_temp_c", "LEVELS"]

LEVELS = ("DEBUG", "INFO", "STATE", "WARN", "ERROR")


def fmt(value) -> str:
    """把字段值变成一行文本里安全、紧凑的写法。

    - 布尔 -> 1/0
    - 浮点 -> 最多 3 位小数，去掉末尾 0
    - 枚举 -> 名字（如 OFFBOARD / SEARCH）
    - None -> `-`
    - 元组/列表 -> 用 `/` 连接（如姿态 0.4/-0.2/87.3）
    - 字符串里的空格 -> `_`，避免字段被空格切开
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Enum):
        return str(value.name)
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text if text not in ("", "-0") else "0"
    if isinstance(value, (tuple, list)):
        return "/".join(fmt(v) for v in value)
    text = str(value)
    if text == "":
        return "-"
    return text.replace(" ", "_").replace("\n", "_").replace("=", ":")


def _jsonable(value):
    """把字段值转成 JSON 能序列化的类型，尽量保留原始数值。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    # numpy 标量：np.float32 / np.int64 等
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def read_cpu_temp_c():
    """读 CPU/SoC 温度（摄氏度）。读不到返回 None，不影响飞行。"""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="ascii") as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return None


class FlightLogger:
    """双写日志器。一个实例 = 一次飞行会话。"""

    def __init__(
        self,
        log_dir: str = "logs",
        prefix: str = "flight",
        console: bool = True,
        state_hz: float = 2.0,
    ):
        if state_hz <= 0:
            raise ValueError("state_hz 必须大于 0")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{prefix}_{stamp}_{os.getpid()}"
        self.session = base
        self.text_path = self.log_dir / f"{base}.log"
        self.jsonl_path = self.log_dir / f"{base}.jsonl"

        self.console = console
        self.state_hz = float(state_hz)
        self._t0 = time.monotonic()
        self._last_state = 0.0
        self._lock = threading.Lock()
        self._closed = False

        self._text = open(self.text_path, "w", encoding="utf-8", buffering=1)
        self._jsonl = open(self.jsonl_path, "w", encoding="utf-8", buffering=1)

        self.log(
            "session_start",
            session=base,
            text=str(self.text_path),
            jsonl=str(self.jsonl_path),
        )

    # ---------------- 对外接口 ----------------

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def log(self, msg: str = "", level: str = "INFO", **fields):
        """写一行日志。`msg` 是事件名/人话，`fields` 是结构化字段。"""
        level = str(level).upper()
        if level not in LEVELS:
            level = "INFO"
        self._emit(level, str(msg), fields)

    def event(self, name: str, level: str = "INFO", **fields):
        """事件日志的别名，语义更清楚。"""
        self.log(name, level=level, **fields)

    def state(self, **fields):
        """状态快照，按 state_hz 限频。字段由调用方决定。"""
        now = time.monotonic()
        if now - self._last_state < 1.0 / self.state_hz:
            return
        self._last_state = now
        # 状态行不重复写 "state" 这个词，省一点宽度。
        self.log("", level="STATE", **fields)

    def close(self):
        if self._closed:
            return
        self.log("session_end", duration_s=round(self.elapsed, 3))
        with self._lock:
            self._closed = True
            try:
                self._text.close()
            finally:
                self._jsonl.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---------------- 内部 ----------------

    def _emit(self, level: str, msg: str, fields: dict):
        now = datetime.now()
        ts = now.strftime("%H:%M:%S.%f")[:-3]
        body = msg
        if fields:
            field_text = " ".join(f"{k}={fmt(v)}" for k, v in fields.items())
            body = f"{body} {field_text}".strip()
        line = f"[{level}][{ts}]({body})"

        record = {
            "ts": now.isoformat(timespec="milliseconds"),
            "t": round(self.elapsed, 3),
            "level": level,
            "msg": msg,
        }
        record.update({k: _jsonable(v) for k, v in fields.items()})
        json_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

        with self._lock:
            if self._closed:
                return
            self._text.write(line + "\n")
            self._jsonl.write(json_line + "\n")
            if level in ("WARN", "ERROR"):
                self._text.flush()
                self._jsonl.flush()
        if self.console:
            print(line, flush=True)
