#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".venv/bin/activate" ]; then
  echo ".venv not found. Run scripts/setup.sh first."
  exit 1
fi

. .venv/bin/activate
pytest --maxfail=1 --disable-warnings -q
