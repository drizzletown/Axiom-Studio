#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
WORKSPACE="${1:-$(pwd)/.axiom-demo}"
mkdir -p "$WORKSPACE"
python -m axiom --workspace "$WORKSPACE" check examples/two_account.ax --out "$WORKSPACE/two_account.ir.json"
python -m axiom --workspace "$WORKSPACE" plan examples/two_account.ax
python -m axiom --workspace "$WORKSPACE" verify examples/two_account.ax
python -m axiom --workspace "$WORKSPACE" gate examples/two_account.ax --target model
set +e
python -m axiom --workspace "$WORKSPACE" gate examples/two_account.ax --target cpp
cpp_code=$?
python -m axiom --workspace "$WORKSPACE" verify examples/broken_conservation.ax
broken_code=$?
set -e
if [ "$cpp_code" -ne 4 ] || [ "$broken_code" -ne 2 ]; then
    echo 'FAIL: unexpected exit codes' >&2
    exit 1
fi
python -m axiom --workspace "$WORKSPACE" impact --from-spec examples/two_account.ax --to-spec examples/broken_conservation.ax
python -m axiom --workspace "$WORKSPACE" evidence
python -m pytest -q tests
echo 'DEMO PASSED: model accepted; C++ blocked; broken property rejected; evidence invalidated.'
