"""Portable LightGBM text model and explicit sigmoid calibration parameters."""

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit, logit

from factorygraph.io import verify_artifacts


def calibrate(probabilities: np.ndarray, parameters: dict[str, float]) -> np.ndarray:
    logits = logit(np.clip(probabilities, 1e-7, 1 - 1e-7))
    return expit(parameters["slope"] * logits + parameters["intercept"])


class Predictor:
    """Accept precomputed causal features in the saved order, without label columns."""

    def __init__(self, run_dir: Path) -> None:
        verify_artifacts(run_dir, ["model.txt", "calibration.json", "feature_contract.json"])
        self.contract = json.loads((run_dir / "feature_contract.json").read_text())
        self.parameters = json.loads((run_dir / "calibration.json").read_text())
        self.model = lgb.Booster(model_file=str(run_dir / "model.txt"))
        if self.model.feature_name() != self.contract["columns"]:
            raise ValueError("Model and feature contract disagree")

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        columns = self.contract["columns"]
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"Missing features: {sorted(missing)}")
        values = frame[columns].to_numpy(dtype=float)
        if np.isinf(values).any():
            raise ValueError("Infinite features are not supported; NaN encodes unknown history")
        probabilities = self.model.predict(frame[columns], num_threads=self.contract["n_jobs"])
        return calibrate(probabilities, self.parameters)
