"""Official Chronos-2 inference with local verified pretrained weights."""

import json
import time
from typing import Any

import numpy as np

from factorygraph.io import sha256
from factorygraph.phase3.config import Phase3Config
from factorygraph.phase3.sequences import Window

REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"
WEIGHTS_SHA256 = "ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42"


def validate_output(values: np.ndarray, shape: tuple[int, ...]) -> None:
    if values.shape != shape or not np.isfinite(values).all():
        raise ValueError(f"Invalid forecast shape/values: {values.shape}; expected {shape}")
    if (np.diff(values, axis=-1) < -1e-5).any():
        raise ValueError("Crossed quantiles; output cannot define a valid prediction interval")


class ChronosAdapter:
    def __init__(self, config: Phase3Config) -> None:
        self.config = config
        self.pipeline: Any = None
        self.torch: Any = None

    def load(self) -> dict[str, Any]:
        self.pipeline = None
        started = time.perf_counter()
        manifest = json.loads((self.config.model_dir / "manifest.json").read_text())
        if manifest["revision"] != REVISION:
            raise ValueError("Unaudited checkpoint revision")
        for filename, record in manifest["files"].items():
            if sha256(self.config.model_dir / filename) != record["sha256"]:
                raise ValueError(f"Checkpoint integrity failure: {filename}")
        if manifest["files"]["model.safetensors"]["sha256"] != WEIGHTS_SHA256:
            raise ValueError("Checkpoint is not the audited pretrained model")
        import torch
        from chronos import Chronos2Pipeline

        self.torch = torch
        torch.set_num_threads(self.config.cpu_threads)
        torch.manual_seed(self.config.seed)
        if self.config.device not in {"cpu", "cuda"}:
            raise ValueError("Explicit CPU or CUDA device required")
        if self.config.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable; no device fallback")
        self.pipeline = Chronos2Pipeline.from_pretrained(
            str(self.config.model_dir),
            device_map=self.config.device,
            torch_dtype=torch.float32,
            local_files_only=True,
        )
        self.pipeline.model.eval()
        self.sync()
        return {
            "load_seconds_including_integrity_and_imports": time.perf_counter() - started,
            "parameters": sum(p.numel() for p in self.pipeline.model.parameters()),
            "model_context_limit": self.pipeline.model_context_length,
            "device": self.config.device,
        }

    def sync(self) -> None:
        if self.config.device == "cuda":
            self.torch.cuda.synchronize()

    def predict(self, windows: list[Window]) -> tuple[np.ndarray, dict[str, float]]:
        if self.pipeline is None or not windows:
            raise RuntimeError("Loaded pretrained model and nonempty windows required")
        started = time.perf_counter()
        for window in windows:
            if window.source_max >= window.issue:
                raise ValueError("Context contains observations unavailable at forecast issue")
            if window.values.shape != (len(self.config.channels), self.config.context_length):
                raise ValueError("Multivariate context shape mismatch")
            if window.channels != self.config.channels or not np.isfinite(window.values).all():
                raise ValueError("Channel identity or finite context check failed")
        inputs = np.stack([window.values for window in windows])
        preprocessing = time.perf_counter() - started
        events = []

        def before(module: Any, args: Any) -> None:
            event = (
                self.torch.cuda.Event(enable_timing=True)
                if self.config.device == "cuda"
                else (time.perf_counter())
            )
            if self.config.device == "cuda":
                event.record()
            events.append([event, None])

        def after(module: Any, args: Any, output: Any) -> None:
            event = (
                self.torch.cuda.Event(enable_timing=True)
                if self.config.device == "cuda"
                else (time.perf_counter())
            )
            if self.config.device == "cuda":
                event.record()
            events[-1][1] = event

        hooks = [
            self.pipeline.model.register_forward_pre_hook(before),
            self.pipeline.model.register_forward_hook(after),
        ]
        self.sync()
        inference_start = time.perf_counter()
        try:
            with self.torch.inference_mode():
                quantiles, _ = self.pipeline.predict_quantiles(
                    inputs,
                    prediction_length=self.config.horizon,
                    quantile_levels=self.config.quantiles,
                    batch_size=len(windows) * len(self.config.channels),
                    context_length=self.config.context_length,
                    cross_learning=False,
                )
            self.sync()
        finally:
            for hook in hooks:
                hook.remove()
        inference = time.perf_counter() - inference_start
        post_start = time.perf_counter()
        forecasts = np.stack([q.detach().float().cpu().numpy() for q in quantiles])
        validate_output(
            forecasts,
            (
                len(windows),
                len(self.config.channels),
                self.config.horizon,
                len(self.config.quantiles),
            ),
        )
        neural = sum(
            a.elapsed_time(b) / 1000 if self.config.device == "cuda" else b - a for a, b in events
        )
        return forecasts, {
            "preprocessing_seconds": preprocessing,
            "sdk_inference_seconds": inference,
            "neural_forward_seconds": neural,
            "postprocessing_seconds": time.perf_counter() - post_start,
            "total_seconds": time.perf_counter() - started,
        }

    def memory(self) -> dict[str, Any]:
        import psutil

        info = psutil.Process().memory_info()
        return {
            "process_rss_bytes": info.rss,
            "process_peak_working_set_bytes": getattr(info, "peak_wset", None),
            "gpu_peak_allocated_bytes": self.torch.cuda.max_memory_allocated()
            if (self.config.device == "cuda")
            else None,
            "gpu_peak_reserved_bytes": self.torch.cuda.max_memory_reserved()
            if (self.config.device == "cuda")
            else None,
        }
