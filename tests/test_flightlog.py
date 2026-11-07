# -*- coding: utf-8 -*-
"""飞行日志格式的回归测试：不接飞控、不接相机也能跑。

    python tests/test_flightlog.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vnav.flightlog import FlightLogger, fmt  # noqa: E402


def test_fmt():
    assert fmt(None) == "-"
    assert fmt(True) == "1"
    assert fmt(False) == "0"
    assert fmt(1.23456) == "1.235"
    assert fmt(1.0) == "1"
    assert fmt(-0.0) == "0"
    assert fmt((0.4, -0.2, 87.3)) == "0.4/-0.2/87.3"
    assert fmt("lost target") == "lost_target"


def test_text_and_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        fl = FlightLogger(log_dir=tmp, prefix="t", console=False, state_hz=100.0)
        fl.log("hello", level="INFO", a=1, b=2.5, c=True, d=None, e=(1, 2.5), f="x y")
        fl.event("warn_evt", level="WARN", reason="lost target")
        fl.state(x=1)
        fl.state(x=2)  # 100Hz 限频：这一行应被丢掉
        fl.close()

        text = fl.text_path.read_text(encoding="utf-8")
        lines = text.strip().splitlines()

        assert any(line.startswith("[INFO][") for line in lines)
        assert any(line.startswith("[WARN][") for line in lines)
        assert any(line.startswith("[STATE][") for line in lines)
        assert any("hello a=1 b=2.5 c=1 d=- e=1/2.5 f=x_y" in line for line in lines)
        assert any("warn_evt reason=lost_target" in line for line in lines)
        assert sum(1 for line in lines if line.startswith("[STATE][")) == 1
        assert any("session_start" in line for line in lines)
        assert any("session_end" in line for line in lines)

        json_lines = fl.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        records = [json.loads(line) for line in json_lines]
        assert records[0]["msg"] == "session_start"
        hello = next(r for r in records if r["msg"] == "hello")
        assert hello["level"] == "INFO"
        assert hello["a"] == 1
        assert hello["b"] == 2.5
        assert hello["c"] is True
        assert hello["d"] is None
        assert hello["e"] == [1, 2.5]
        assert hello["f"] == "x y"
        assert isinstance(hello["t"], (int, float))
        assert any(r["msg"] == "state" or r["level"] == "STATE" for r in records)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[X ] {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
