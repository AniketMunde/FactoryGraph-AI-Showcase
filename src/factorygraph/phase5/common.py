"""Frozen Phase 5 inputs, exact split keys and historical integrity."""

import json
from pathlib import Path

import pandas as pd
import yaml
from pydantic import Field

from factorygraph.config import Settings
from factorygraph.config import load_config as baseline_config
from factorygraph.features import chronological_split
from factorygraph.io import sha256, write_json

KEYS = ["machineID", "datetime"]
SPLIT_ROWS = {"train": 162798, "calibration": 23945, "validation": 23146, "test": 72633}
POLICIES = [
    "docs/PHASE5_RESEARCH_PROTOCOL.md",
    "docs/PHASE5_TEMPORAL_FEATURE_POLICY.md",
    "docs/PHASE5_ABLATION_DESIGN.md",
]
GROUPS = {
    "A0": ["A"],
    "A1": ["A", "B"],
    "A2": ["A", "C"],
    "A3": ["A", "D"],
    "A4": ["A", "E"],
    "A5": ["A", "B", "D"],
    "A6": ["A", "C", "D"],
}


class Config(Settings):
    run_dir: Path = Path("artifacts/phase5/study")
    seed: int = 42
    batch_origins: int = 16
    max_forecast_seconds: int = 1800
    bootstrap_draws: int = Field(default=200, ge=20)
    alert_budgets: list[float] = [0.005, 0.01, 0.02]


def load_config(path=Path("configs/phase5/study.yaml")) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))


def verify_prior() -> int:
    protected = json.loads(Path("artifacts/phase5/protected.json").read_text())
    for path, digest in protected.items():
        if sha256(Path(path)) != digest:
            raise ValueError(f"Protected Phase 1–4 file changed: {path}")
    return len(protected)


def audit(config: Config):
    from factorygraph.phase4.source import verify_preservation

    verify_preservation()
    previous = json.loads(Path("docs/results/phase4.json").read_text())
    for field in ["source_sha256", "implementation_sha256"]:
        for path, digest in previous[field].items():
            if sha256(Path(path)) != digest:
                raise ValueError("Accepted Phase 4 implementation changed")
    root = Path("artifacts/phase4")
    for path, digest in json.loads((root / "artifact_manifest.json").read_text()).items():
        if sha256(root / path) != digest:
            raise ValueError("Accepted Phase 4 artifact changed")
    target = Path("artifacts/phase5/protected.json")
    if not target.exists():
        paths = set()
        for root in [
            "artifacts/baseline",
            "artifacts/phase2",
            "artifacts/phase3",
            "artifacts/phase4",
            "data/raw/azure",
            "data/processed/azure",
            "data/models",
            "data/phase3",
            "src/factorygraph",
            "tests",
            "configs",
            "requirements",
        ]:
            paths.update(
                p
                for p in Path(root).rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and "phase5" not in p.parts
                and p.name != "phase5.lock"
            )
        paths.update(
            p
            for p in Path("docs").rglob("*")
            if p.is_file()
            and p.name not in {"ARCHITECTURE.md", "ROADMAP.md", "DECISIONS.md"}
            and "phase5" not in p.name.lower()
        )
        paths.add(Path("requirements.lock"))
        write_json(target, {p.as_posix(): sha256(p) for p in sorted(paths)})
    return {"status": "passed", "protected_files": verify_prior()}


def splits(labels=False) -> dict[str, pd.DataFrame]:
    columns = None if labels else [*KEYS, "label_end"]
    frame = pd.read_parquet("data/processed/azure/snapshots.parquet", columns=columns)
    result = chronological_split(frame, baseline_config(Path("configs/baseline.yaml")).split)
    for name, data in result.items():
        if len(data) != SPLIT_ROWS[name] or data.duplicated(KEYS).any():
            raise ValueError("Accepted split identity/size changed")
    return result


def exact_join(left: pd.DataFrame, right: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if left.duplicated(KEYS).any() or right.duplicated(KEYS).any():
        raise ValueError("Duplicate feature keys")
    joined = left[KEYS].merge(
        right[[*KEYS, *columns]], on=KEYS, how="left", validate="one_to_one", indicator=True
    )
    if not (joined._merge == "both").all() or len(right) != len(left):
        raise ValueError("Feature populations do not match exactly")
    return joined.drop(columns="_merge")


def verify_registration(config: Config):
    record = json.loads((config.run_dir / "registration.json").read_text())
    if config.model_dump(mode="json") != record["config"]:
        raise ValueError("Phase 5 config differs from registration")
    for path, digest in record["policies_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("Registered temporal/ablation policy changed")
    for name, digest in record["membership_sha256"].items():
        if sha256(config.run_dir / name) != digest:
            raise ValueError("Registered membership changed")
    return record


def save_manifest(directory: Path):
    write_json(
        directory / "artifact_manifest.json",
        {
            p.relative_to(directory).as_posix(): sha256(p)
            for p in directory.rglob("*")
            if p.is_file() and p.name != "artifact_manifest.json"
        },
    )
