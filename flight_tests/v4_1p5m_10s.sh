#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/common.sh" 1.5 10 0.15 0.04
