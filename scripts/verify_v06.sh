#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=studio:engine/src
python -m pytest -q studio/tests/test_batches.py studio/tests/test_batches_http.py
printf '\nOptional real native C++ end-to-end test (trusted Linux/WSL2 only):\n'
printf 'PYTHONPATH=studio:engine/src python scripts/batch_demo.py --output studio/batch_demo_report.json\n'
