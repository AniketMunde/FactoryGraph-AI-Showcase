"""Predeclared, bounded Phase 2 experiment settings."""

from pathlib import Path

import yaml
from pydantic import Field, model_validator

from factorygraph.config import Settings


class Phase2Config(Settings):
    baseline_dir: Path = Path("artifacts/baseline")
    run_dir: Path = Path("artifacts/phase2/kumo-pilot")
    model_dir: Path = Path("data/models/phase2/kumo-small")
    checkpoint_repo: str = "nvidia/Kumo-Tabular"
    checkpoint_revision: str = "3c3e10bbdb590ace29e7026847f92db3c603096d"
    checkpoint_file: str = "small/classifier.pt"
    context_sizes: list[int] = [512, 2048]
    cohort_machines: int = Field(default=10, ge=1)
    seed: int = 42
    batch_size: int = Field(default=64, ge=1)
    num_estimators: int = Field(default=1, ge=1)
    cpu_threads: int = Field(default=4, ge=1)
    device: str = "cuda"
    max_projected_seconds: float = Field(default=1800, gt=0)
    minimum_free_ram_gb: float = Field(default=3, gt=0)
    calibration: str = "none"

    @model_validator(mode="after")
    def supported(self) -> "Phase2Config":
        if not self.context_sizes or any(n < 2 for n in self.context_sizes):
            raise ValueError("Context sizes must be at least two")
        if sorted(set(self.context_sizes)) != self.context_sizes:
            raise ValueError("Context sizes must be unique and increasing")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("Device must be explicitly cpu or cuda; no silent fallback")
        if self.calibration != "none":
            raise ValueError("This registered study uses raw probabilities; no fitted calibration")
        if self.checkpoint_file != "small/classifier.pt":
            raise ValueError("This adapter is audited for the Kumo small classifier only")
        return self


def load_config(path: Path) -> Phase2Config:
    return Phase2Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
