# gf-admission policy core (0.1.0.dev1)

Development milestone only. This wheel contains pure classification, feature,
pressure and queue primitives. It has **no Motor activation hooks, broker, RPC,
WaitHub, live FeatureProvider or shadow/enforce runtime**. Installing it does not
change routing. Do not deploy this milestone as an admission experiment.

The root slo-patch 0.2.0 distribution remains unchanged. This package does not
register a vLLM plugin and does not import Motor, torch, HTTP clients or engines.

From the repository root:

```sh
.venv/bin/python scripts/package/build_gf_admission_core.py --output artifacts/gf-admission/core-build
```

The builder creates a standalone source tree and wheel in a new directory,
includes SHA256 for the source/wheel, and runs a clean import from that wheel.
It uses the current interpreter's setuptools, with no dependency download.
Generated files are development artifacts, not a Huawei release.

Policy parameters have no production defaults. The example values in tests
are synthetic test conditions; 20/1 and .8/1.5 are prototype reference rules.
Classifiers must be called once per logical request by a future central broker;
the pure classifier does not itself implement identity or transaction retention.
Queue removal is not native/FG release. Pressure is in FG score units and is
not a prediction of milliseconds. Snapshot age uses one monotonic clock domain.

Python syntax target: 3.10+. Actually tested interpreter versions and remaining
acceptance work are recorded in `docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md`.
