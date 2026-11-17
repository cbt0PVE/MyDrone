#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.0 8 0.14 0.05
