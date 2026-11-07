# -*- coding: utf-8 -*-
"""起飞前点选目标：板子起一个本地网页，手机/PC 在画面上框人。

    python3 tools/enroll_server.py --source 0 --out ~/target.json --port 8000

然后手机/PC 打开 http://<板子IP>:8000 ，在画面上拖一个框，点“锁定目标”。
保存的 target.json 给 run_tracking.py --target 用。

注意：
- 这是本地网页，不需要互联网；板子开热点或和手机/PC 同一局域网即可。
- 只用于起飞前点选；点完可以关服务，再启动跟踪（摄像头不能被两个进程同时占）。
- 没有鉴权，别在不可信网络长期开着。
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vnav.camera import open_camera  # noqa: E402
from vnav.config import Config  # noqa: E402


PAGE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Orange Pi 目标点选</title>
<style>
  html,body { margin:0; background:#111; color:#eee; font-family:system-ui,sans-serif; }
  header { padding:10px 14px; background:#1b1b1b; position:sticky; top:0; z-index:2; }
  header b { color:#7CFC9A; }
  #wrap { position:relative; max-width:960px; margin:0 auto; touch-action:none; }
  #video { display:block; width:100%; height:auto; }
  #overlay { position:absolute; inset:0; width:100%; height:100%; touch-action:none; cursor:crosshair; }
  #bar { max-width:960px; margin:0 auto; padding:10px 14px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  button { padding:10px 16px; font-size:16px; border:0; border-radius:8px; background:#2d7ef7; color:#fff; }
  button.secondary { background:#444; }
  #status { color:#ffd166; font-size:14px; }
  .hint { color:#aaa; font-size:13px; padding:0 14px 10px; max-width:960px; margin:0 auto; }
</style>
</head>
<body>
<header>Orange Pi 目标点选 · <b>在画面上拖一个框，框住实验人员</b></header>
<div id="wrap">
  <img id="video" src="/stream" alt="camera">
  <canvas id="overlay"></canvas>
</div>
<div id="bar">
  <button id="lock">重新选择</button>
  <button id="shutdown" class="secondary">关闭服务</button>
  <span id="status">等待框选…</span>
</div>
<div class="hint">框选后会自动保存 target.json；然后关闭服务，再启动 run_tracking.py --target。</div>
<script>
const img = document.getElementById('video');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
let start = null, cur = null, selected = null, sending = false;

function fit() {
  const r = img.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(r.width));
  canvas.height = Math.max(1, Math.round(r.height));
  draw();
}
window.addEventListener('resize', fit);
img.addEventListener('load', fit);
setTimeout(fit, 300);

function pos(e) {
  const r = canvas.getBoundingClientRect();
  return [
    Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
    Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
  ];
}
function boxOf(a, b) {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}
function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const box = start && cur ? boxOf(start, cur) : selected;
  if (!box) return;
  const x = box[0] * canvas.width, y = box[1] * canvas.height;
  const w = (box[2] - box[0]) * canvas.width, h = (box[3] - box[1]) * canvas.height;
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#7CFC9A';
  ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = 'rgba(124,252,154,0.15)';
  ctx.fillRect(x, y, w, h);
}

canvas.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  canvas.setPointerCapture(e.pointerId);
  start = pos(e); cur = start; selected = null; draw();
  statusEl.textContent = '拖动框住目标…';
});
canvas.addEventListener('pointermove', (e) => {
  if (!start) return;
  e.preventDefault();
  cur = pos(e); draw();
});
canvas.addEventListener('pointerup', (e) => {
  if (!start) return;
  e.preventDefault();
  cur = pos(e);
  const b = boxOf(start, cur);
  start = null; cur = null;
  if (b[2] - b[0] < 0.02 || b[3] - b[1] < 0.02) {
    selected = null; draw(); statusEl.textContent = '框太小，重画一次';
    return;
  }
  selected = b; draw();
  send(b);
});

async function send(b) {
  if (sending) return;
  sending = true;
  statusEl.textContent = '保存中…';
  try {
    const r = await fetch('/select', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({bbox_norm: b})
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || '保存失败');
    statusEl.textContent = '已锁定：' + b.map(v => v.toFixed(3)).join(', ');
  } catch (e) {
    statusEl.textContent = '保存失败：' + e.message;
  } finally {
    sending = false;
  }
}

document.getElementById('lock').addEventListener('click', () => {
  selected = null; start = null; cur = null; draw();
  fetch('/reset', {method: 'POST'}).catch(() => {});
  statusEl.textContent = '重新框选…';
});
document.getElementById('shutdown').addEventListener('click', () => {
  statusEl.textContent = '服务关闭中…';
  fetch('/shutdown', {method: 'POST'}).catch(() => {});
});
</script>
</body>
</html>
"""


class CameraFeed:
    def __init__(self, source, width=640):
        cfg = Config()
        cfg.camera_source = source
        cfg.show_window = False
        self.cap = open_camera(cfg)
        self.width = int(width)
        self.lock = threading.Lock()
        self.frame = None
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            if self.width and frame.shape[1] > self.width:
                scale = self.width / frame.shape[1]
                frame = cv2.resize(
                    frame,
                    (self.width, int(frame.shape[0] * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            with self.lock:
                self.frame = frame.copy()
            time.sleep(0.01)

    def latest(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def close(self):
        self.running = False
        try:
            self.cap.release()
        except Exception:
            pass


class EnrollServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, handler, feed, out_path):
        super().__init__(addr, handler)
        self.feed = feed
        self.out_path = out_path
        self.selection = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/stream":
            self._stream()
        elif path == "/status":
            self._send(200, json.dumps({"selection": self.server.selection}), "application/json")
        else:
            self._send(404, "not found")

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                frame = self.server.feed.latest()
                if frame is None:
                    time.sleep(0.05)
                    continue
                ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    continue
                data = jpg.tobytes()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n")
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.06)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/shutdown":
            self._send(200, json.dumps({"ok": True}), "application/json")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/reset":
            self.server.selection = None
            self._send(200, json.dumps({"ok": True}), "application/json")
            return
        if path != "/select":
            self._send(404, "not found")
            return

        try:
            n = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            bbox = [float(v) for v in data["bbox_norm"]]
            if len(bbox) != 4:
                raise ValueError("bbox_norm 需要 4 个数")
            x1, y1, x2, y2 = bbox
            if not all(0.0 <= v <= 1.0 for v in bbox):
                raise ValueError("bbox_norm 必须在 0–1")
            if x2 <= x1 or y2 <= y1:
                raise ValueError("x2/y2 必须大于 x1/y1")
            frame = self.server.feed.latest()
            h, w = (frame.shape[:2] if frame is not None else (0, 0))
            payload = {
                "bbox_norm": [x1, y1, x2, y2],
                "frame_width": int(w),
                "frame_height": int(h),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            out = self.server.out_path
            os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.server.selection = payload
            print("SELECT", out, payload["bbox_norm"], flush=True)
            self._send(200, json.dumps({"ok": True, "bbox_norm": bbox}), "application/json")
        except Exception as e:
            self._send(400, json.dumps({"error": str(e)}), "application/json")


def main():
    ap = argparse.ArgumentParser(description="起飞前点选目标（本地 MJPEG 网页）")
    ap.add_argument("--source", default="0", help="摄像头序号 0 或视频路径/RTSP")
    ap.add_argument("--out", default="target.json", help="保存 bbox_norm 的 json")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--width", type=int, default=640, help="推流宽度，默认 640")
    args = ap.parse_args()

    source = int(args.source) if str(args.source).isdigit() else args.source
    feed = CameraFeed(source, args.width)
    server = EnrollServer(("0.0.0.0", args.port), Handler, feed, args.out)

    print(f"[OK] 点选服务已启动：http://<板子IP>:{args.port}", flush=True)
    print(f"     保存到：{os.path.abspath(args.out)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        feed.close()
        server.server_close()
        print("服务已关闭", flush=True)


if __name__ == "__main__":
    main()
