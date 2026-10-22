"""Freeze scheduler-owned state before the next schedule can mutate it."""
from dataclasses import dataclass
import json
import time


@dataclass(frozen=True)
class BatchSnapshot:
    engine_epoch: str
    batch_seq: int
    payloads: tuple[tuple[str, str], ...]


def freeze_snapshot(output, requests: dict, engine_epoch: str, batch_seq: int) -> BatchSnapshot:
    groups: dict[str, list[dict]] = {}
    predicted = getattr(output, "predicted_batch_exec_time", None)
    for rid, count in output.num_scheduled_tokens.items():
        req = requests.get(rid)
        if req is None:
            continue
        meta = (req.kv_transfer_params or {}).get("fgjsq")
        if not isinstance(meta, dict):
            continue
        url = meta["event_url"]
        item = {k: meta[k] for k in ("reservation_id", "coordinator_epoch", "attempt_seq",
                                     "instance_id", "endpoint_id", "generation")}
        item.update(engine_request_id=rid, num_prompt_tokens=req.num_prompt_tokens,
                    num_computed_tokens=req.num_computed_tokens - count,
                    num_scheduled_tokens=count, num_remaining_tokens=max(req.num_tokens - req.num_computed_tokens, 0),
                    predicted_exec_ms=round(float(predicted if predicted is not None else
                                                   getattr(req, "predicted_ttft_entry", 0) * 1000), 3))
        groups.setdefault(url, []).append(item)
    captured = time.time()
    payloads = tuple((url, json.dumps({"schema_version": 1, "engine_epoch": engine_epoch, "batch_seq": batch_seq,
                                      "captured_at": captured, "requests": items}, allow_nan=False))
                     for url, items in groups.items())
    return BatchSnapshot(engine_epoch, batch_seq, payloads)
