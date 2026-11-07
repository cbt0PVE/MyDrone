#!/usr/bin/env bash
# WSL x86_64: install Python 3.10 + RKNN Toolkit2 2.3.2 for ONNX -> RKNN conversion.
set -euo pipefail

echo "=== python / conda ==="
python3 --version
if [ ! -x "$HOME/miniconda3/bin/conda" ]; then
    echo "=== install miniconda ==="
    curl -L --retry 3 --max-time 900 -o "$HOME/miniconda.sh" \
        https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh
    bash "$HOME/miniconda.sh" -b -p "$HOME/miniconda3"
fi

echo "=== create py3.10 env ==="
if [ ! -x "$HOME/miniconda3/envs/rknn/bin/python" ]; then
    "$HOME/miniconda3/bin/conda" create -y -n rknn python=3.10
fi
PY="$HOME/miniconda3/envs/rknn/bin/python"
PIP="$HOME/miniconda3/envs/rknn/bin/pip"
"$PY" --version

echo "=== install rknn-toolkit2 2.3.2 (no torch yet) ==="
"$PIP" install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir --no-deps "rknn-toolkit2==2.3.2"
"$PIP" install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir \
    "numpy==1.26.4" "onnx==1.16.1" "onnxruntime>=1.10.0" "setuptools<81" \
    "opencv-python-headless>=4.5.5.64" "protobuf>=4.21.6,<=4.25.4" \
    "psutil>=5.9.0" "ruamel.yaml>=0.17.21" "scipy>=1.9.3" \
    "tqdm>=4.64.1" "fast-histogram>=0.11"

echo "=== import test ==="
if "$PY" -c "from rknn.api import RKNN; print('RKNN_OK')"; then
    echo "RKNN import OK without torch"
else
    echo "=== install CPU torch (toolkit may need it at import) ==="
    "$PIP" install --no-cache-dir torch==2.4.0 \
        --index-url https://download.pytorch.org/whl/cpu || \
        "$PIP" install --no-cache-dir torch==2.4.0
    "$PY" -c "from rknn.api import RKNN; print('RKNN_OK')"
fi

echo "=== versions ==="
"$PY" -c "import numpy, onnx, cv2; print('numpy', numpy.__version__); print('onnx', onnx.__version__); print('cv2', cv2.__version__)"
echo "DONE"
