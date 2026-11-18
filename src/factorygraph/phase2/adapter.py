"""Genuine pretrained Kumo inference, with an optional dependency boundary."""

import json
import time
import urllib.request
from contextlib import nullcontext
from typing import Any, Protocol

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase2.config import Phase2Config
from factorygraph.phase2.context import KEYS, assert_context_eligible, validate_keys

CHECKPOINT_SHA256 = "1ff91f484e19021aaf7d9eff6cc07e6d95a60b4aaad473e83e2ab2c3bfd2b617"


class ModelLoadError(RuntimeError):
    """A real checkpoint or runtime could not be loaded; no fallback is permitted."""


class ModelInferenceError(RuntimeError):
    """Pretrained inference failed or returned invalid class probabilities."""


class TabularAdapter(Protocol):
    def load(self) -> dict[str, Any]: ...
    def set_context(self, context: pd.DataFrame) -> dict[str, float]: ...
    def predict(self, query: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]: ...


def validate_features(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    expected = set(columns) | set(KEYS)
    if not frame.columns.is_unique or set(frame.columns) != expected:
        raise ValueError("Query/context feature schema must exactly match keys plus saved features")
    validate_keys(frame)
    values = frame[columns].copy()
    if any(not pd.api.types.is_numeric_dtype(values[name]) for name in columns):
        raise ValueError("Features must be numeric; model_code is the saved categorical code")
    if np.isinf(values.to_numpy(dtype=float)).any():
        raise ValueError("Infinite feature values are invalid")
    if not values.model_code.isin([1, 2, 3, 4]).all():
        raise ValueError("Unknown model_code category")
    # Fixed domain vocabulary; no vocabulary is inferred from held-out rows.
    values["model_code"] = pd.Categorical(values.model_code, categories=[1, 2, 3, 4])
    return values


def validate_probabilities(probabilities: np.ndarray, rows: int) -> np.ndarray:
    values = np.asarray(probabilities, dtype=float)
    if values.shape != (rows, 2):
        raise ModelInferenceError(
            f"Expected binary class probabilities ({rows},2), got {values.shape}"
        )
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ModelInferenceError("Nonfinite or out-of-range class probabilities")
    if not np.allclose(values.sum(axis=1), 1, atol=1e-5):
        raise ModelInferenceError("Class probabilities are not normalized")
    return values


def download_checkpoint(config: Phase2Config) -> None:
    """Acquire only the selected public checkpoint and notices at an immutable revision."""
    root = config.model_dir
    manifest_path = root / "checkpoint_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["revision"] != config.checkpoint_revision:
            raise ModelLoadError("Checkpoint directory belongs to a different revision")
        for name, record in manifest["files"].items():
            if sha256(root / name) != record["sha256"]:
                raise ModelLoadError(f"Checkpoint integrity failure: {name}")
        return
    records = {}
    for name in [config.checkpoint_file, "LICENSE", "README.md", "config.json"]:
        url = (
            f"https://huggingface.co/{config.checkpoint_repo}/resolve/"
            f"{config.checkpoint_revision}/{name}"
        )
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "FactoryGraph-Phase2/0.1"})
            with (
                urllib.request.urlopen(request, timeout=120) as response,
                partial.open("wb") as out,
            ):
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            partial.replace(path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        records[name] = {"url": url, "bytes": path.stat().st_size, "sha256": sha256(path)}
    write_json(
        manifest_path,
        {
            "repo": config.checkpoint_repo,
            "revision": config.checkpoint_revision,
            "license": "OpenMDW-1.1",
            "files": records,
        },
    )


class KumoAdapter:
    """Use SDK architecture, strict pretrained state loading, and official fit/predict caching.

    The SDK's fit builds inference state; it does not optimize model parameters.
    The checkpoint is loaded locally to avoid an unpinned SDK tag lookup/network fallback.
    """

    def __init__(self, config: Phase2Config, columns: list[str]) -> None:
        self.config = config
        self.columns = columns
        self.model: Any = None
        self.context: pd.DataFrame | None = None
        self.torch: Any = None
        self.sdm: Any = None

    def _sync(self) -> None:
        if self.config.device == "cuda":
            self.torch.cuda.synchronize()

    def _amp(self) -> Any:
        return (
            self.torch.autocast("cuda", dtype=self.torch.float16)
            if (self.config.device == "cuda")
            else nullcontext()
        )

    def load(self) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            import sdm
            import torch

            self.torch, self.sdm = torch, sdm
            torch.set_num_threads(self.config.cpu_threads)
            torch.manual_seed(self.config.seed)
            if self.config.device == "cuda" and not torch.cuda.is_available():
                raise ModelLoadError("CUDA was requested but is unavailable")
            manifest = json.loads((self.config.model_dir / "checkpoint_manifest.json").read_text())
            if manifest["revision"] != self.config.checkpoint_revision:
                raise ModelLoadError("Checkpoint revision does not match the registered experiment")
            path = self.config.model_dir / self.config.checkpoint_file
            expected = manifest["files"][self.config.checkpoint_file]["sha256"]
            if expected != CHECKPOINT_SHA256 or sha256(path) != expected:
                raise ModelLoadError("Checkpoint checksum mismatch")
            # Exact counterpart of upstream _load_from_pretrained; no SDK monkeypatch.
            self.model = sdm.models.KumoTabular(
                task="classification", size="small", pretrained=False, device="cpu"
            )
            state = torch.load(path, map_location="cpu", weights_only=True)
            self.model.models["classification"].load_state_dict(state, strict=True)
            del state
            self.model.to(self.config.device).eval()
            self._sync()
            return {
                "load_seconds_including_optional_imports": time.perf_counter() - start,
                "parameters": sum(p.numel() for p in self.model.parameters()),
                "device": self.config.device,
            }
        except ModelLoadError:
            raise
        except Exception as exc:
            self.model = None
            raise ModelLoadError(f"Kumo checkpoint/runtime loading failed: {exc}") from exc

    def set_context(self, context: pd.DataFrame) -> dict[str, float]:
        if self.model is None:
            raise ModelLoadError("Load the pretrained model before constructing context")
        start = time.perf_counter()
        validate_keys(context)
        if set(context.label.unique()) != {0, 1}:
            raise ValueError("Context must contain both binary classes")
        values = validate_features(context[KEYS + self.columns], self.columns)
        target = pd.DataFrame({"target": pd.Categorical(context.label, categories=[0, 1])})
        try:
            x = self.sdm.TableTensor.from_pandas(
                values, stypes=self.sdm.infer_stypes(values), device=self.config.device
            )
            y = self.sdm.TableTensor.from_pandas(
                target, stypes={"target": "categorical"}, device=self.config.device
            )
            self._sync()
            tensor_seconds = time.perf_counter() - start
            start = time.perf_counter()
            with self.torch.inference_mode(), self._amp():
                self.model.fit(
                    x,
                    y,
                    num_estimators=self.config.num_estimators,
                    generator=self.torch.Generator(device=self.config.device).manual_seed(
                        self.config.seed
                    ),
                )
            self._sync()
            self.context = context[KEYS + ["label_end"]].copy()
            return {
                "context_tensor_seconds": tensor_seconds,
                "context_cache_seconds": time.perf_counter() - start,
            }
        except Exception as exc:
            self.context = None
            raise ModelInferenceError(f"Kumo context construction failed: {exc}") from exc

    def predict(self, query: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
        if self.model is None or self.context is None:
            raise ModelInferenceError("Pretrained model and eligible context are required")
        start = time.perf_counter()
        assert_context_eligible(self.context, query)
        values = validate_features(query, self.columns)
        try:
            x = self.sdm.TableTensor.from_pandas(
                values, stypes=self.sdm.infer_stypes(values), device=self.config.device
            )
            self._sync()
            tensor_seconds = time.perf_counter() - start
            forward_start = time.perf_counter()
            neural_calls = []
            hooks = []
            if hasattr(self.model, "models"):

                def before_forward(module: Any, inputs: Any) -> None:
                    if self.config.device == "cuda":
                        event = self.torch.cuda.Event(enable_timing=True)
                        event.record()
                    else:
                        event = time.perf_counter()
                    neural_calls.append([event, None])

                def after_forward(module: Any, inputs: Any, output: Any) -> None:
                    if self.config.device == "cuda":
                        event = self.torch.cuda.Event(enable_timing=True)
                        event.record()
                    else:
                        event = time.perf_counter()
                    neural_calls[-1][1] = event

                neural_model = self.model.models["classification"]
                hooks = [
                    neural_model.register_forward_pre_hook(before_forward),
                    neural_model.register_forward_hook(after_forward),
                ]
            try:
                with self.torch.inference_mode(), self._amp():
                    output = self.model.predict(x)
            finally:
                for hook in hooks:
                    hook.remove()
            self._sync()
            forward_seconds = time.perf_counter() - forward_start
            neural_seconds = (
                sum(
                    start_event.elapsed_time(end_event) / 1000
                    if self.config.device == "cuda"
                    else end_event - start_event
                    for start_event, end_event in neural_calls
                )
                if neural_calls
                else None
            )
            # Class names come from the categorical context vocabulary, never position guesses.
            probabilities = np.column_stack(
                [
                    output[:, str(label)].numerical.detach().float().cpu().numpy().reshape(-1)
                    for label in [0, 1]
                ]
            )
            probabilities = validate_probabilities(probabilities, len(query))
            return probabilities, {
                "query_tensor_and_safety_seconds": tensor_seconds,
                "sdk_predict_seconds": forward_seconds,
                "neural_forward_seconds": neural_seconds,
                "total_seconds": time.perf_counter() - start,
            }
        except ModelInferenceError:
            raise
        except Exception as exc:
            raise ModelInferenceError(f"Kumo pretrained prediction failed: {exc}") from exc
