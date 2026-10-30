#!/usr/bin/env bash
# Local CPU regression for the g5 + admission rc2 development baseline.
# Only the disposable Motor development copy is prepared; no services are started.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${G5_PYTHON:-$ROOT/.venv/bin/python}"
MOTOR="$ROOT/artifacts/build/motor-rc2-validation"
OUT="${GF_VALIDATION_OUT:-$ROOT/artifacts/local-validation/rc2}"
if [[ ! -x "$PYTHON" ]]; then
    echo "Set G5_PYTHON to an existing environment with Motor CPU test dependencies." >&2
    exit 1
fi
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
export PATH="$(dirname "$PYTHON"):$PATH"
export PYTHONPATH="$ROOT/src:$MOTOR"
export PIP_NO_INDEX=1
"$PYTHON" "$ROOT/scripts/dev/prepare_sources.py"
# An already validated rc2 copy must not be fed to the g5-only installer.
if ! "$PYTHON" -c 'from gf_admission.compatibility import validate_runtime; validate_runtime()' >/dev/null 2>&1; then
    "$PYTHON" "$ROOT/scripts/dev/prepare_g5_motor.py" --output "$MOTOR" --with-tests
fi
PATCH="$ROOT/patches/motor/g5-gf-admission-0.1.0rc2.patch"
if ! git -C "$MOTOR" apply --reverse --check "$PATCH" 2>/dev/null; then
    git -C "$MOTOR" apply --check "$PATCH"
    git -C "$MOTOR" apply "$PATCH"
fi
"$PYTHON" -c 'from gf_admission.compatibility import validate_runtime; print("Runtime source contract:", validate_runtime())'
cd "$MOTOR"
bash tests/run_tests.sh --serial "$ROOT/tests/unit" "$ROOT/tests/integration" \
    --color=no "--junitxml=$OUT/project.xml" 2>&1 | tee "$OUT/project.log"
bash tests/run_tests.sh --serial tests/node_manager/test_config.py tests/config \
    tests/node_manager/core/services/native_engine/backends/test_config_contract.py \
    tests/node_manager/core/services/native_engine/backends/vllm/test_config.py \
    tests/coordinator/scheduler/test_scheduler_client.py \
    tests/coordinator/scheduler/test_scheduler_server_main.py \
    tests/coordinator/router/test_unified_pd_router.py \
    --color=no "--junitxml=$OUT/motor.xml" 2>&1 | tee "$OUT/motor.log"
echo "rc2 CPU regression completed: $OUT. Native SHM/NPU/performance remain onsite checks."
