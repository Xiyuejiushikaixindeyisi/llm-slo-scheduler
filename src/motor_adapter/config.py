"""One explicit configuration file shared by Coordinator subprocesses."""
from dataclasses import dataclass, fields
from functools import lru_cache
import json
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    event_url: str = ""
    max_num_seqs: int = 24
    retention: float = 0.05
    reserve_window_s: float = 30.0
    tombstone_s: float = 3600.0
    max_records: int = 100000
    rpc_attempts: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if self.enabled:
            url = urlparse(self.event_url)
            if url.scheme not in ("http", "https") or not url.netloc or url.path != "/fgjsq/v1/events":
                raise ValueError("event_url must be an absolute /fgjsq/v1/events HTTP URL")
        if self.max_num_seqs <= 0 or not 0 <= self.retention < 1:
            raise ValueError("invalid policy configuration")
        if not 0 < self.reserve_window_s < self.tombstone_s or self.max_records <= 0 or self.rpc_attempts <= 0:
            raise ValueError("invalid lifecycle configuration")


@lru_cache(maxsize=1)
def get_config() -> Config:
    path = os.getenv("FGJSQ_CONFIG")
    if not path:
        return Config()
    values = json.loads(Path(path).read_text())
    unknown = set(values) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError("unknown FGJSQ config fields: " + ", ".join(sorted(unknown)))
    return Config(**values)


def enabled() -> bool:
    return get_config().enabled


def validate_motor(config) -> None:
    if not enabled():
        return
    for section, key in (("standby_config", "enable_master_standby"),
                         ("render_config", "enabled"),
                         ("token_obfuscation_config", "enabled"),
                         ("scheduler_config", "enable_pd_separation_fallback_to_hybrid")):
        if getattr(getattr(config, section, None), key, False):
            raise ValueError("FGJSQ v1 does not support " + section + "." + key)
