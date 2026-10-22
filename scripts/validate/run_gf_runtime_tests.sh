#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MOTOR="${GF_TEST_MOTOR_ROOT:-$ROOT/reference-motor}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PIP_NO_INDEX=1
mkdir -p "$ROOT/artifacts/gf-admission"
cd "$MOTOR"
bash tests/run_tests.sh --serial "$ROOT/tests/unit/test_admission_core.py" \
  "$ROOT/tests/unit/test_admission_broker.py" "$ROOT/tests/unit/test_admission_install.py" \
  "$ROOT/tests/unit/test_gf_experiment_tools.py" "$ROOT/tests/unit/test_fgjsq.py" "$ROOT/tests/integration/test_motor_adapter.py" \
  "$ROOT/tests/integration/test_admission_runtime.py" --color=no \
  "--junitxml=$ROOT/artifacts/gf-admission/runtime.xml"
