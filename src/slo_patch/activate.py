"""P-only general plugin; preserve the existing optional D chat compatibility hook."""
import os

_applied = False


def activate() -> None:
    global _applied
    if _applied:
        return
    role = os.getenv("SLO_PATCH_ROLE", "").lower()
    if role not in ("", "prefill", "decode"):
        raise ValueError("SLO_PATCH_ROLE must be prefill or decode")
    if role != "prefill":
        if os.getenv("P3D_TOLERATE_BAD_TOOL_ARGS", "0") == "1":
            from slo_patch.patch_runtime import _patch_chat_utils_tool_args
            _patch_chat_utils_tool_args()
        _applied = True
        return
    if int(os.getenv("ENABLE_VLLM_TTFT_SLO_MS", "0")) != 0:
        raise ValueError("This baseline requires SLO=0; admission mechanisms are pending")
    if os.getenv("ENABLE_BATCH_REPORTER", "0") != "1":
        raise ValueError("P baseline requires ENABLE_BATCH_REPORTER=1")
    from slo_patch.compatibility import verify_engine
    verify_engine()
    from slo_patch.patch_runtime import apply_all
    apply_all()
    _applied = True
