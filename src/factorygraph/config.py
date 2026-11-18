"""Validated, serializable experiment settings. Paths are relative to the working directory."""

from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureConfig(Settings):
    windows_hours: list[int] = [3, 24, 72]
    snapshot_hours: int = Field(default=3, ge=1, le=24)
    horizon_hours: int = Field(default=24, ge=1)

    @model_validator(mode="after")
    def valid_windows(self) -> "FeatureConfig":
        if not self.windows_hours or any(w <= 0 for w in self.windows_hours):
            raise ValueError("Feature windows must be positive and nonempty")
        if len(set(self.windows_hours)) != len(self.windows_hours):
            raise ValueError("Feature windows must be unique")
        return self


class SplitConfig(Settings):
    start: str
    train_end: str
    calibration_end: str
    validation_end: str
    test_end: str

    @model_validator(mode="after")
    def ordered(self) -> "SplitConfig":
        times = [pd.Timestamp(v) for v in self.model_dump().values()]
        if any(t.tzinfo is None for t in times):
            raise ValueError("Split timestamps require an explicit timezone")
        if any(a >= b for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("Split boundaries must be strictly increasing")
        return self


class ModelConfig(Settings):
    n_estimators: int = Field(default=200, ge=1)
    learning_rate: float = Field(default=0.05, gt=0)
    num_leaves: int = Field(default=31, ge=2)
    min_child_samples: int = Field(default=100, ge=1)
    reg_lambda: float = Field(default=1.0, ge=0)
    n_jobs: int = Field(default=4, ge=1)
    random_state: int = 42


class ExperimentConfig(Settings):
    raw_dir: Path = Path("data/raw/azure")
    processed_dir: Path = Path("data/processed/azure")
    run_dir: Path = Path("artifacts/baseline")
    features: FeatureConfig = FeatureConfig()
    split: SplitConfig
    model: ModelConfig = ModelConfig()
    alert_budget_fraction: float = Field(default=0.01, gt=0, lt=1)
    cooldown_hours: int = Field(default=24, ge=1)


def load_config(path: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
