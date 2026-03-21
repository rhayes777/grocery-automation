#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PUBLIC_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=24.0" "setuptools>=68" wheel --index-url "$PUBLIC_INDEX_URL"
python -m pip install -e ".[dev]" --index-url "$PUBLIC_INDEX_URL"

echo "Bootstrap complete."
echo "Activate with: source .venv/bin/activate"
