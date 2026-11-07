#!/usr/bin/env bash
# Orange Pi (aarch64, Python 3.10): user-level pip + RKNN Lite2 + numpy.
set -uo pipefail

echo "=== pip bootstrap ==="
cd /tmp
if ! command -v pip3 >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/pip3" ]; then
    curl -sS -L --retry 3 --max-time 120 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    python3 /tmp/get-pip.py --user
fi
export PATH="$HOME/.local/bin:$PATH"
python3 -m pip --version

echo "=== numpy / psutil / yaml ==="
python3 -m pip install --user --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple "numpy==1.26.4" "psutil" "ruamel.yaml"

echo "=== rknn-toolkit-lite2 2.3.2 (aarch64 cp310) ==="
python3 -m pip install --user --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --no-deps "rknn-toolkit-lite2==2.3.2"

echo "=== opencv (optional, may be slow) ==="
if ! python3 -c "import cv2" 2>/dev/null; then
    python3 -m pip install --user --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple "opencv-python-headless==4.10.0.84" || echo "OPENCV_PIP_FAILED"
fi

echo "=== check ==="
python3 - <<'PY'
import sys
print("python", sys.version.split()[0])
try:
    import numpy
    print("numpy", numpy.__version__)
except Exception as e:
    print("numpy ERR", e)
try:
    import cv2
    print("cv2", cv2.__version__)
except Exception as e:
    print("cv2 ERR", e)
try:
    from rknnlite.api import RKNNLite
    print("rknnlite OK")
except Exception as e:
    print("rknnlite ERR", e)
PY
echo "DONE"
