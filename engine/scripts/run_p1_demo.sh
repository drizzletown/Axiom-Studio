#!/usr/bin/env bash
# Reproducible P1 acceptance. Only run trusted candidate source files.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
WORKSPACE="${1:-$(mktemp -d -t axiom-p1-demo-XXXXXX)}"
mkdir -p "$WORKSPACE"
echo "Workspace: $WORKSPACE"
ax() { python -m axiom --workspace "$WORKSPACE" "$@"; }
ax check examples/two_account.ax > "$WORKSPACE/check.json"
ax verify examples/two_account.ax > "$WORKSPACE/model.json"
ax cpp-verify --trusted-local examples/two_account.ax --candidate cpp/correct.cpp --binding cpp/binding.json > "$WORKSPACE/correct.json"
ax cpp-gate examples/two_account.ax --candidate cpp/correct.cpp --binding cpp/binding.json > "$WORKSPACE/gate.json"
for variant in broken_mapping broken_boundary broken_overflow broken_frozen_input; do
  set +e
  ax cpp-verify --trusted-local examples/two_account.ax --candidate "cpp/$variant.cpp" --binding cpp/binding.json > "$WORKSPACE/$variant.json"
  rc=$?
  set -e
  if [ "$rc" -ne 2 ]; then echo "Unexpected failure code for $variant: $rc"; exit 1; fi
done
set +e
ax cpp-verify --trusted-local examples/two_account.ax --candidate cpp/broken_compile.cpp --binding cpp/binding.json > "$WORKSPACE/broken_compile.json"
rc=$?
set -e
[ "$rc" -eq 3 ] || { echo "Expected compile failure as Unknown (3), got $rc"; exit 1; }
set +e
ax cpp-gate examples/two_account.ax --candidate cpp/correct.cpp --binding cpp/binding.json --optimization 2 > "$WORKSPACE/changed_flags_gate.json"
rc=$?
set -e
[ "$rc" -eq 4 ] || { echo "Expected stale flags gate to be blocked (4), got $rc"; exit 1; }
python - "$WORKSPACE" <<'PY'
import json,sys,pathlib
w=pathlib.Path(sys.argv[1]);get=lambda x:json.loads((w/(x+'.json')).read_text())
assert get('model')['verification']['outcome']=='Bounded'
assert get('correct')['verification']['outcome']=='Tested'
assert get('gate')['decision']=='Approved'
for n in ['broken_mapping','broken_boundary','broken_overflow','broken_frozen_input']:
    assert get(n)['verification']['outcome']=='Violated'
assert get('broken_compile')['verification']['outcome']=='Unknown'
assert get('changed_flags_gate')['decision']=='Blocked'
print(json.dumps({'p0_model':get('model')['verification']['outcome'],
    'p1_cpp':get('correct')['verification']['outcome'],
    'tested_reachable_pairs':get('correct')['verification']['scope']['tested_pairs'],
    'observed_calls_per_variant':get('correct')['verification']['scope']['observed_calls_per_variant'],
    'p1_gate':get('gate')['decision'],
    'faults':{n:get(n)['verification']['reason'] for n in ['broken_mapping','broken_boundary','broken_overflow','broken_frozen_input']},
    'compile_failure':get('broken_compile')['verification']['outcome'],
    'changed_flags_gate':get('changed_flags_gate')['decision'],
    'results_dir':str(w)},indent=2))
PY
