#!/usr/bin/env bash
# CPU regression entry point. It never starts engines or installs NPU packages.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${G5_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    echo "Set G5_PYTHON to a Python environment with the Motor CPU test dependencies." >&2
    exit 1
fi
OUT="$ROOT/artifacts/local-validation"
mkdir -p "$OUT"
export PATH="$(dirname "$PYTHON"):$PATH"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
# Motor's wrapper checks dependencies; do not download packages during verification.
export PIP_NO_INDEX="${PIP_NO_INDEX:-1}"
"$PYTHON" "$ROOT/scripts/dev/prepare_sources.py"
"$PYTHON" "$ROOT/scripts/dev/prepare_g5_motor.py" --with-tests
"$PYTHON" "$ROOT/scripts/validate/verify_g5_baseline.py" --output "$OUT/fingerprints.json"
cd "$ROOT/artifacts/build/motor-g5"
bash tests/run_tests.sh --serial "$ROOT/tests/unit" "$ROOT/tests/integration" \
    --color=no "--junitxml=$OUT/project.xml" 2>&1 | tee "$OUT/project.log"
bash tests/run_tests.sh --serial tests/node_manager/test_config.py tests/config \
    tests/node_manager/core/services/native_engine/backends/test_config_contract.py \
    tests/node_manager/core/services/native_engine/backends/vllm/test_config.py \
    --color=no "--junitxml=$OUT/motor.xml" 2>&1 | tee "$OUT/motor.log"
echo "CPU checks passed. Results: $OUT. NPU correctness and performance require onsite validation."
