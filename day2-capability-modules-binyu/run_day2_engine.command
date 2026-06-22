#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="/Users/zcmbp/.pyenv/versions/3.10.17/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
"$PYTHON_BIN" pocket_review_engine.py
