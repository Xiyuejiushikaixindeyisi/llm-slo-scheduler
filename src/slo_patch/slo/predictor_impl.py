# 来源：260807 dev 仓 ascend_vllm/patch/slo/predictor_impl.py —— 逐行复制，
# 唯一改动：import 路径 ascend_vllm.patch.slo.predictor -> slo_patch.slo.predictor
# -*- coding: utf-8 -*-
"""
Optimized In-Process Python Predictor — sub-1ms predict latency.

Optimizations over previous version:
1. Split Pipeline into separate scaler + raw GBR — eliminates Pipeline overhead
2. Inline scaler transform (pre-computed mean_/scale_) — eliminates sklearn StandardScaler overhead
3. No _model_lock — Python GIL guarantees atomic reference assignment
4. n_estimators=300, lr=0.05 (same quality as original, inline scaler saves ~220us)

Architecture:
  Training: scaler.fit_transform + GBR.fit (background thread, in-process)
  Predict:  inline scaler + GBR.predict (in-process, no lock, no IPC)
"""

import os
import time
import threading
import pickle
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional, Any

import numpy as np
import pandas as pd

from lightgbm import LGBMRegressor
from sklearn.preprocessing import StandardScaler

try:
    from vllm.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger("vllm")

from slo_patch.slo.predictor import PredictorInterface, PredictorConfig


@dataclass
class PurePythonPredictorConfig(PredictorConfig):
    csv_path: str = ""
    save_dir: str = "predictor_results"
    target_col: str = "execute_time_ms"

    length_bucket_size: int = 1000
    cache_bucket_size: float = 0.2
    bucket_maxlen: int = 100

    random_state: int = 42
    min_total_train_samples: int = 50

    n_estimators: int = 300
    max_depth: int = 5
    learning_rate: float = 0.05
    min_child_samples: int = 5
    subsample: float = 0.85

    warmup_batches: int = 2
    update_interval_batches: int = 100

    model_path: Optional[str] = None


FEATURE_COLS = [
    "N_uncached",
    "B",
    "L_avg",
    "cache_hit_rate",
    "prefill_intensity",
    "N_cached",
    "Cross_Attention_Proxy",
    "Self_Attention_Proxy",
]

class _ModelSnapshot:
    __slots__ = ('gbr', 'scaler_mean', 'scaler_scale')

    def __init__(self, gbr, scaler_mean, scaler_scale):
        self.gbr = gbr
        self.scaler_mean = scaler_mean
        self.scaler_scale = scaler_scale


class BucketedSlidingWindow:
    def __init__(
            self,
            length_bucket_size: int = 1000,
            cache_bucket_size: float = 0.2,
            maxlen: int = 300,
    ):
        self.length_bucket_size = int(length_bucket_size)
        self.cache_bucket_size = float(cache_bucket_size)
        self.maxlen = int(maxlen)
        self.buffers: Dict[Tuple[int, int], deque] = defaultdict(
            lambda: deque(maxlen=self.maxlen)
        )
        self._dirty = False
        self._cached_df = None

    def bucket_key_from_values(self, avg_prompt_length: float, cache_hit_rate: float) -> Tuple[int, int]:
        l_val = max(0.0, float(avg_prompt_length))
        h_val = float(np.clip(cache_hit_rate, 0.0, 1.0))
        l_bucket = int(l_val // self.length_bucket_size)
        max_cache_bucket = int(np.ceil(1.0 / self.cache_bucket_size)) - 1
        h_bucket = int(h_val // self.cache_bucket_size)
        h_bucket = min(max(h_bucket, 0), max_cache_bucket)
        return l_bucket, h_bucket

    def bucket_label(self, key: Tuple[int, int]) -> str:
        l_bucket, h_bucket = key
        l_start = l_bucket * self.length_bucket_size
        l_end = (l_bucket + 1) * self.length_bucket_size
        h_start = h_bucket * self.cache_bucket_size
        h_end = min(1.0, (h_bucket + 1) * self.cache_bucket_size)
        return f"L[{l_start},{l_end})_H[{h_start:.1f},{h_end:.1f}]"

    def add_sample(self, sample: Dict[str, Any]) -> None:
        key = self.bucket_key_from_values(sample["avg_prompt_length"], sample["cache_hit_rate"])
        item = sample.copy()
        item["bucket_key"] = key
        item["bucket_label"] = self.bucket_label(key)
        self.buffers[key].append(item)
        self._dirty = True

    def __len__(self) -> int:
        return sum(len(d) for d in self.buffers.values())

    def to_dataframe(self) -> pd.DataFrame:
        if not self._dirty and self._cached_df is not None:
            return self._cached_df
        rows: List[Dict[str, Any]] = []
        for key in sorted(self.buffers.keys()):
            rows.extend(list(self.buffers[key]))
        self._cached_df = pd.DataFrame(rows)
        self._dirty = False
        return self._cached_df


def compute_features(
        batch_size: int,
        avg_prompt_length: float,
        cache_hit_rate: float,
        total_scheduled_tokens: Optional[int] = None,
        total_cached_tokens: Optional[int] = None,
) -> Dict[str, float]:
    B = float(batch_size)
    L_avg = float(avg_prompt_length)
    cache_hit_rate = float(np.clip(cache_hit_rate, 0.0, 1.0))

    if total_cached_tokens is None:
        total_cached_tokens = int(B * L_avg * cache_hit_rate)
    if total_scheduled_tokens is None:
        total_scheduled_tokens = int(B * L_avg - total_cached_tokens)

    N_uncached = float(total_scheduled_tokens)
    N_cached = float(total_cached_tokens)

    prefill_intensity = N_uncached / (B + 1e-6)

    safe_b = max(B, 1.0)
    Cross_Attention_Proxy = (N_uncached * N_cached) / safe_b
    Self_Attention_Proxy = (N_uncached ** 2) / safe_b

    return {
        "N_uncached": N_uncached,
        "B": B,
        "L_avg": L_avg,
        "cache_hit_rate": cache_hit_rate,
        "prefill_intensity": prefill_intensity,
        "N_cached": N_cached,
        "Cross_Attention_Proxy": Cross_Attention_Proxy,
        "Self_Attention_Proxy": Self_Attention_Proxy,
        "avg_prompt_length": avg_prompt_length,
    }


class PurePythonPredictor(PredictorInterface):
    """
    Optimized in-process predictor: sub-1ms predict latency.

    Key optimizations:
    - Split scaler + raw GBR (no Pipeline)
    - Inline scaler transform (pre-computed mean_/scale_, no sklearn overhead)
    - No _model_lock (GIL guarantees atomic ref assignment)
    - n_estimators=300, lr=0.05 (same quality as original)
    """

    def __init__(self, config: PredictorConfig = None):
        if config is None:
            self.config = PurePythonPredictorConfig()
        elif isinstance(config, PurePythonPredictorConfig):
            self.config = config
        else:
            self.config = PurePythonPredictorConfig()
            for attr in dir(config):
                if not attr.startswith('_') and hasattr(self.config, attr):
                    setattr(self.config, attr, getattr(config, attr))
        # [fg-3p3d 2026-09-29] E1/E2 warmup 方案 A（用户签核）：env 注入预训练模型
        # 路径，加载成功即 warmup_done=True（见下方 model_path 加载块）。
        # 默认空=关闭，行为与上游完全一致；两臂统一传同一路径保证初始条件一致。
        _pretrained = os.getenv("SLO_PREDICTOR_MODEL_PATH", "")
        if _pretrained and not self.config.model_path:
            self.config.model_path = _pretrained

        self.buffer = BucketedSlidingWindow(
            length_bucket_size=self.config.length_bucket_size,
            cache_bucket_size=self.config.cache_bucket_size,
            maxlen=self.config.bucket_maxlen,
        )

        self.batch_count = 0
        self.batches_since_update = 0
        self.model_version = 0
        self.warmup_done = False

        self.prediction_history: deque = deque(maxlen=1000)

        self.config.save_dir = self.config.save_dir.rstrip("/") + "_" + time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time()*1000)%1000:03d}"
        self._eval_log_path = os.path.join(self.config.save_dir, "model_eval_log.csv")
        os.makedirs(self.config.save_dir, exist_ok=True)

        self._snapshot: Optional[_ModelSnapshot] = None
        self._model_ready = False
        self._closed = False

        self._training_event = threading.Event()
        self._training_start_time = 0.0
        self._training_timeout = 60.0

        self._predict_count = 0

        if hasattr(self.config, 'model_path') and self.config.model_path:
            if os.path.exists(self.config.model_path):
                try:
                    with open(self.config.model_path, 'rb') as f:
                        saved = pickle.load(f)
                    if isinstance(saved, dict):
                        scaler = saved['scaler']
                        gbr = saved['gbr']
                    else:
                        scaler = saved.named_steps['scaler']
                        gbr = saved.named_steps['gbr']
                    scaler_mean = scaler.mean_.astype(np.float64)
                    scaler_scale = np.maximum(scaler.scale_.astype(np.float64), 1e-8)
                    self._snapshot = _ModelSnapshot(gbr, scaler_mean, scaler_scale)
                    self._model_ready = True
                    self.warmup_done = True
                    logger.info("[slo] loaded pre-trained model from %s (scaler+gbr split)",
                                self.config.model_path)
                except Exception as e:
                    logger.warning("[slo] failed to load pre-trained model: %s", e)

        import atexit
        atexit.register(self.close)

    def predict(
            self,
            batch_size: int,
            avg_prompt_length: float,
            cache_hit_rate: float,
    ) -> float:
        if not self._model_ready or self._snapshot is None:
            N_uncached = batch_size * avg_prompt_length * (1 - cache_hit_rate)
            return N_uncached * 0.01

        t0 = time.monotonic()
        try:
            snap = self._snapshot

            # Inline compute_features — avoid dict/list/pandas overhead
            B = float(batch_size)
            L_avg = float(avg_prompt_length)
            chr_ = min(max(float(cache_hit_rate), 0.0), 1.0)
            cached_int = int(B * L_avg * chr_)
            uncached_int = int(B * L_avg - cached_int)
            N_uncached_f = float(uncached_int)
            N_cached_f = float(cached_int)
            prefill_intensity = N_uncached_f / (B + 1e-6)
            safe_b = max(B, 1.0)
            cross_ap = (N_uncached_f * N_cached_f) / safe_b
            self_ap = (N_uncached_f * N_uncached_f) / safe_b

            # Pure numpy scale + predict — no pandas DataFrame
            X = np.array([[N_uncached_f, B, L_avg, chr_, prefill_intensity,
                           N_cached_f, cross_ap, self_ap]], dtype=np.float64)
            X_s = (X - snap.scaler_mean) / snap.scaler_scale
            pred_ms = float(snap.gbr.predict(X_s)[0])

            N_uncached = batch_size * avg_prompt_length * (1 - cache_hit_rate)
            if pred_ms < 0.0:
                pred_ms = 0.001
            if pred_ms > 60000:
                pred_ms = 60000

            self._predict_count += 1
            if self._predict_count % 100 == 0:
                dt_total = (time.monotonic() - t0) * 1e6
                logger.info("[slo] predict #%d: total=%.0fus pred_ms=%.1f",
                            self._predict_count, dt_total, pred_ms)
            return pred_ms
        except Exception as e:
            logger.warning("[slo] in-process predict failed: %s, falling back to heuristic", e)
            N_uncached = batch_size * avg_prompt_length * (1 - cache_hit_rate)
            return N_uncached * 0.01

    def update(
            self,
            actual_ttft: float,
            predicted_ttft: float,
            batch_size: int,
            avg_prompt_length: float,
            cache_hit_rate: float,
    ) -> None:
        t1 = time.monotonic()
        self.batch_count += 1
        self.batches_since_update += 1

        features = compute_features(
            batch_size=batch_size,
            avg_prompt_length=avg_prompt_length,
            cache_hit_rate=cache_hit_rate,
        )

        sample = {
            **features,
            self.config.target_col: actual_ttft,
            "batch_id": self.batch_count,
        }
        self.buffer.add_sample(sample)

        self.prediction_history.append({
            "batch_id": self.batch_count,
            "actual_ms": actual_ttft,
            "predicted_ms": predicted_ttft,
            "error_ms": abs(actual_ttft - predicted_ttft),
        })

        logger.info(
            "[slo] in-predictor update: batch_count=%d, batches_since_update=%d, "
            "warmup_done=%s, warmup_batches=%d, update_interval=%d, "
            "buffer_size=%d, model=%s",
            self.batch_count, self.batches_since_update,
            self.warmup_done, self.config.warmup_batches,
            self.config.update_interval_batches,
            len(self.buffer),
            "ready" if self._model_ready else "not_ready")

        if (
                (not self.warmup_done and self.batch_count >= self.config.warmup_batches)
                or self.batches_since_update >= self.config.update_interval_batches
        ):
            logger.info("[slo] triggering _train_model: warmup_done=%s, batch_count=%d",
                        self.warmup_done, self.batch_count)
            self._train_model()

        t2 = time.monotonic()
        logger.info("[slo] update consumed %.1f ms", (t2 - t1) * 1000)

    def _train_model(self):
        train_df = self.buffer.to_dataframe()

        logger.info("[slo] _train_model: train_df len=%d, min_samples=%d",
                    len(train_df), self.config.min_total_train_samples)

        if len(train_df) < self.config.min_total_train_samples:
            logger.info("[slo] _train_model: not enough samples, skipping")
            return

        if self._training_event.is_set():
            elapsed = time.monotonic() - self._training_start_time
            if elapsed > self._training_timeout:
                logger.warning("[slo] _train_model: previous training stuck for %.1fs, "
                               "force resetting", elapsed)
                self._training_event.clear()
            else:
                logger.info("[slo] _train_model: previous training still running (%.1fs), skipping",
                            elapsed)
                return

        self._training_event.set()
        self._training_start_time = time.monotonic()
        self.batches_since_update = 0
        threading.Thread(target=self._train_model_async, args=(train_df,), daemon=True).start()

    @staticmethod
    def _sample_cpu_snapshot():
        try:
            import psutil
            proc = psutil.Process()
            threads = {}
            for t in proc.threads():
                try:
                    tp = psutil.Process(t.id)
                    threads[t.id] = tp.cpu_times()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return {
                "proc": proc.cpu_times(),
                "total": psutil.cpu_times(),
                "mem": psutil.virtual_memory(),
                "threads": threads,
                "train_tid": threading.current_thread().ident,
            }
        except ImportError:
            return None

    @staticmethod
    def _log_cpu_usage(before, after, wall_ms, extra_msg=""):
        if before is None or after is None:
            logger.info("[slo] _train_model CPU: psutil not available, train_cost=%.1fms%s",
                        wall_ms, extra_msg)
            return
        try:
            import psutil
            wall_s = wall_ms / 1000.0
            ncpu = psutil.cpu_count()

            pu = after["proc"].user - before["proc"].user
            ps_ = after["proc"].system - before["proc"].system
            proc_cores = (pu + ps_) / wall_s if wall_s > 0 else 0.0
            proc_pct = proc_cores / ncpu * 100.0

            tu = after["total"].user - before["total"].user
            ts = after["total"].system - before["total"].system
            total_cores = (tu + ts) / wall_s if wall_s > 0 else 0.0
            total_pct = total_cores / ncpu * 100.0

            mem_mb = psutil.Process().memory_info().rss / 1024 / 1024
            sys_mem = after["mem"]
            sys_mem_pct = sys_mem.percent

            train_tid = before.get("train_tid")
            train_thread_cores = 0.0
            other_thread_cores = 0.0
            n_threads = 0
            b_threads = before.get("threads", {})
            a_threads = after.get("threads", {})
            for tid, bt in b_threads.items():
                at = a_threads.get(tid)
                if at is None:
                    continue
                n_threads += 1
                dt = (at.user - bt.user) + (at.system - bt.system)
                tc = dt / wall_s if wall_s > 0 else 0.0
                if tid == train_tid:
                    train_thread_cores = tc
                else:
                    other_thread_cores += tc

            logger.info(
                "[slo] _train_model CPU: train_cost=%.1fms, "
                "proc_cpu=%.1f cores (%.1f%%), total_cpu=%.1f cores (%.1f%%), "
                "train_thread=%.1f cores, other_threads=%.1f cores (%d threads), "
                "train_mem_rss=%.0fMB, sys_mem=%.0f/%.0fMB (%.1f%%)%s",
                wall_ms, proc_cores, proc_pct,
                total_cores, total_pct,
                train_thread_cores, other_thread_cores, n_threads,
                mem_mb, sys_mem.used / 1024 / 1024, sys_mem.total / 1024 / 1024, sys_mem_pct,
                extra_msg)
        except Exception:
            logger.info("[slo] _train_model CPU: psutil error, train_cost=%.1fms%s",
                        wall_ms, extra_msg)

    def _train_model_async(self, train_df: pd.DataFrame):
        try:
            X_train_df = train_df[FEATURE_COLS].astype(float)
            y_train = train_df[self.config.target_col].astype(float).values

            logger.info("[slo] _train_model_async: fitting scaler+GBR in-process, samples=%d",
                        len(train_df))

            t0 = time.monotonic()
            new_scaler = StandardScaler()
            X_scaled = pd.DataFrame(new_scaler.fit_transform(X_train_df), columns=FEATURE_COLS)

            new_gbr = LGBMRegressor(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                min_child_samples=self.config.min_child_samples,
                subsample=self.config.subsample,
                min_gain_to_split=0.01,
                monotone_constraints=[1, 1, 1, -1, 1, -1, 1, 1],  # N_uncached, B, L_avg, cache_hit_rate, prefill_intensity, N_cached, Cross_Attention_Proxy, Self_Attention_Proxy
                n_jobs=1,
                random_state=self.config.random_state,
                verbose=-1,
            )
            new_gbr.fit(X_scaled, y_train)
            train_ms = (time.monotonic() - t0) * 1000

            y_pred = new_gbr.predict(X_scaled)
            abs_err = np.abs(y_pred - y_train)
            ss_res = np.sum((y_train - y_pred) ** 2)
            ss_tot = np.sum((y_train - np.mean(y_train)) ** 2)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            mape = float(np.mean(np.abs((y_train - y_pred) / (y_train + 1e-8))))

            metrics = {
                "train_samples": int(len(X_scaled)),
                "r2": float(r2),
                "mae": float(np.mean(abs_err)),
                "mape": mape,
                "p50_abs_error": float(np.quantile(abs_err, 0.50)),
                "p90_abs_error": float(np.quantile(abs_err, 0.90)),
                "p95_abs_error": float(np.quantile(abs_err, 0.95)),
                "p99_abs_error": float(np.quantile(abs_err, 0.99)),
            }

            self._snapshot = _ModelSnapshot(
                gbr=new_gbr,
                scaler_mean=new_scaler.mean_.astype(np.float64),
                scaler_scale=np.maximum(new_scaler.scale_.astype(np.float64), 1e-8),
            )
            self._model_ready = True

            self.warmup_done = True
            self.model_version += 1
            self.batches_since_update = 0

            logger.info("[slo] _train_model SUCCESS (in-process): model_version=%d, "
                        "train_cost=%.1fms, r2=%.4f, mae=%.2f, n_estimators=%d — LGBMRegressor!",
                        self.model_version, train_ms, r2, metrics["mae"],
                        self.config.n_estimators)

            self._log_eval_metrics(self._evaluate_model(metrics, self.model_version))

            if self.config.save_dir:
                save_path = os.path.join(self.config.save_dir, "model.pkl")
                try:
                    with open(save_path, 'wb') as f:
                        pickle.dump({'scaler': new_scaler, 'gbr': new_gbr}, f)
                except Exception as e:
                    logger.warning("[slo] failed to save model: %s", e)

        except Exception as e:
            logger.error("[slo] _train_model FAILED: %s", e, exc_info=True)
        finally:
            self._training_event.clear()

    def _evaluate_model(self, metrics: Dict[str, Any], model_version: int) -> Dict[str, Any]:
        return {
            "model_version": model_version,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            **metrics,
        }

    def _log_eval_metrics(self, metrics: Dict[str, Any]):
        eval_log_header = [
            "model_version", "timestamp", "train_samples",
            "r2", "mae", "mape",
            "p50_abs_error", "p90_abs_error", "p95_abs_error", "p99_abs_error",
        ]
        row = [
            str(metrics["model_version"]),
            metrics["timestamp"],
            str(metrics["train_samples"]),
            f"{metrics['r2']:.6f}",
            f"{metrics['mae']:.6f}",
            f"{metrics['mape']:.6f}",
            f"{metrics['p50_abs_error']:.6f}",
            f"{metrics['p90_abs_error']:.6f}",
            f"{metrics['p95_abs_error']:.6f}",
            f"{metrics['p99_abs_error']:.6f}",
        ]
        is_first_write = not os.path.exists(self._eval_log_path)
        mode = "w" if is_first_write else "a"
        with open(self._eval_log_path, mode, encoding="utf-8") as f:
            if is_first_write:
                f.write(",".join(eval_log_header) + "\n")
            f.write(",".join(row) + "\n")

    def close(self):
        if self._closed:
            return
        self._closed = True

    def __del__(self):
        self.close()


def create_predictor(config: Optional[PredictorConfig] = None) -> PredictorInterface:
    if config is None:
        config = PurePythonPredictorConfig()
    return PurePythonPredictor(config)


__all__ = [
    "PurePythonPredictor", "PurePythonPredictorConfig",
    "create_predictor", "FEATURE_COLS", "compute_features",
]