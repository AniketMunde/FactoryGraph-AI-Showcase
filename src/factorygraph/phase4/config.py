"""Validated local graph configuration; secrets are environment-only."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "factorygraph-phase4-v1"


class GraphConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str = Field(default="fg_phase4_full_v1", pattern=r"^fg_phase4_[a-z0-9_]+$")
    raw_dir: Path = Path("data/raw/azure")
    processed_dir: Path = Path("data/processed/azure")
    run_dir: Path = Path("artifacts/phase4/full")
    batch_size: int = Field(default=500, ge=1, le=5000)
    machine_ids: list[int] = Field(default_factory=lambda: list(range(1, 101)))
    query_repeats: int = Field(default=3, ge=1, le=10)
    window_hours: int = Field(default=720, ge=1)

    def digest(self) -> str:
        data = {**self.model_dump(mode="json"), "schema_version": SCHEMA_VERSION}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def load_config(path: Path) -> GraphConfig:
    result = GraphConfig.model_validate(yaml.safe_load(path.read_text()))
    if len(result.machine_ids) != len(set(result.machine_ids)) or any(
        i <= 0 for i in result.machine_ids
    ):
        raise ValueError("Machine membership must contain unique positive IDs")
    return result


def connection() -> tuple[str, str, str]:
    uri = os.environ.get("FACTORYGRAPH_NEO4J_URI", "bolt://127.0.0.1:17687")
    if urlparse(uri).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Phase 4 development connections must be localhost-only")
    user = os.environ.get("FACTORYGRAPH_NEO4J_USER")
    password = os.environ.get("FACTORYGRAPH_NEO4J_PASSWORD")
    if not user or not password:
        raise ValueError("Set environment-based Neo4j user and password")
    return uri, user, password


def timestamp(value) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is None:
        raise ValueError("A timezone-aware cutoff is required")
    return result.tz_convert("UTC")


def milliseconds(value) -> int:
    return timestamp(value).value // 1_000_000
