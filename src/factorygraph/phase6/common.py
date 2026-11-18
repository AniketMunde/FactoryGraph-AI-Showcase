"""Versioned configuration, strict clocks and immutable output helpers."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from factorygraph.io import sha256, write_json
from factorygraph.phase4.config import timestamp

VERSION = "factorygraph-phase6-v1"
RULE_VERSION = "1.0.0"
RULE_IDS = [f"R{i:03}" for i in range(1, 8)]
KEYS = ["machineID", "datetime"]
POLICIES = [
    "docs/PHASE6_ARCHITECTURE.md",
    "docs/PHASE6_EVIDENCE_POLICY.md",
    "docs/PHASE6_RECOMMENDATION_RULES.md",
    "docs/PHASE6_EVALUATION_PROTOCOL.md",
    "configs/phase6/v1.yaml",
    "configs/phase6/rules-v1.json",
    "configs/phase6/case-report-v1.schema.json",
]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = VERSION
    run_dir: Path = Path("artifacts/phase6/study")
    window_hours: int = Field(default=720, ge=1, le=720)
    evidence_limit: int = Field(default=100, ge=1, le=1000)
    fleet_limit: int = Field(default=100, ge=1, le=100)
    rule_version: str = RULE_VERSION
    rule_ids: list[str] = Field(default_factory=lambda: RULE_IDS.copy())
    fallback: str = "disabled"

    def digest(self):
        return digest(self.model_dump(mode="json"))

    def check(self):
        if (
            self.version != VERSION
            or self.rule_version != RULE_VERSION
            or self.rule_ids != RULE_IDS
            or self.fallback != "disabled"
        ):
            raise ValueError("Unrecognized rule configuration or fallback")
        return self


def load_config(path=Path("configs/phase6/v1.yaml"), run_dir=None):
    config = Config.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    if run_dir is not None:
        config = config.model_copy(update={"run_dir": Path(run_dir)})
    return config.check()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def iso(value):
    return None if value is None or pd.isna(value) else timestamp(value).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def manifest(directory):
    directory = Path(directory)
    write_json(
        directory / "artifact_manifest.json",
        {
            p.relative_to(directory).as_posix(): sha256(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file() and p.name != "artifact_manifest.json"
        },
    )
