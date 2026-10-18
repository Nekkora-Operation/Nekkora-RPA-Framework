#!/usr/bin/env sh
# Roda a suíte completa em Linux (contêiner oficial do Playwright 1.63.0, Chromium headless) sobre o HEAD commitado.
# Uso: sh tools/linux.sh   (exige Docker; o resultado vai para reports/evidence/linux-pytest.txt)
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=mcr.microsoft.com/playwright/python:v1.63.0-noble
WORK=$(mktemp -d)
git -C "$ROOT" archive HEAD | tar -x -C "$WORK"
MOUNT="$WORK"; command -v cygpath >/dev/null 2>&1 && MOUNT=$(cygpath -w "$WORK")
MSYS_NO_PATHCONV=1 docker run --rm -v "$MOUNT:/w" -w /w "$IMAGE" sh -c '
  (apt-get update -qq && apt-get install -y -qq python3.12-venv >/dev/null) 2>&1 | tail -1
  python3 --version && python3 -m venv /tmp/v && /tmp/v/bin/pip install -q -e ".[dev]" -c constraints/dev.txt 2>&1 | tail -3
  /tmp/v/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -25' | tee "$ROOT/reports/evidence/linux-pytest.txt"
rm -rf "$WORK"
