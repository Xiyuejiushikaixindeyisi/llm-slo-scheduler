# gf-admission 0.1.0rc1

Experimental runtime candidate: policy core, Mgmt broker, worker client, bounded Motor feature adapter.
Default off. Requires the separate, exact-hash-checked incremental Motor/g5 hook patch.
No vLLM plugin entrypoint. Does not replace slo-patch, engines, predictor or FG policy.

Use scripts/package/build_gf_runtime_bundle.py for a complete review/validation bundle.
The historical core-only builder is retained for reproducing older milestones and is not the runtime delivery entry.

Configuration and local/onsite acceptance boundaries: docs/engineering/GF_ADMISSION_RUNTIME_GUIDE.md.
