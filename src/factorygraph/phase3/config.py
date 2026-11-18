"""Fixed Phase 3 study configuration."""

from pathlib import Path

import yaml
from pydantic import Field

from factorygraph.config import Settings


class Phase3Config(Settings):
    run_dir: Path = Path("artifacts/phase3/azure")
    model_dir: Path = Path("data/models/phase3/chronos-2")
    telemetry_path: Path = Path("data/raw/azure/PdM_telemetry.csv")
    channels: list[str] = ["volt", "rotate", "pressure", "vibration"]
    context_length: int = Field(default=168, ge=24)
    horizon: int = Field(default=24, ge=1, le=24)
    origin_stride_hours: int = Field(default=24, ge=1)
    batch_origins: int = Field(default=16, ge=1)
    device: str = "cuda"
    seed: int = 42
    cpu_threads: int = 4
    max_seconds: float = 1800
    validation_start: str = "2015-09-01T00:00Z"
    test_start: str = "2015-10-01T00:00Z"
    test_end: str = "2016-01-01T00:00Z"
    scale_end: str = "2015-08-01T00:00Z"
    quantiles: list[float] = [0.1, 0.5, 0.9]


def load_config(path: Path) -> Phase3Config:
    config = Phase3Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if config.device not in {"cuda", "cpu"} or config.quantiles != [0.1, 0.5, 0.9]:
        raise ValueError("Explicit supported device and registered quantiles required")
    return config
