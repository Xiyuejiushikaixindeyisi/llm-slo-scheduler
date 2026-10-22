"""slo_patch: minimal SLO predictor/scheduler port from 260807 ascend_vllm dev repo.

Entry point (vllm.general_plugins): slo_patch.activate:activate
Effect switches (per-instance):
  - additional_config.scheduler_with_predictor_enable=true -> scheduler_cls swapped
  - env ENABLE_VLLM_TTFT_SLO_MS / ENABLE_BATCH_REPORTER     -> EngineCore.step instrumented
All off -> inert wrapper only (no-op for G0 baseline).
"""

__version__ = "0.1.0"