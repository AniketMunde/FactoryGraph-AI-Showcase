"""Read-only access to the accepted Phase 1 benchmark and exact paired membership."""

import json
from pathlib import Path

import pandas as pd

from factorygraph.config import ExperimentConfig
from factorygraph.features import chronological_split
from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase2.config import Phase2Config
from factorygraph.phase2.context import (
    KEYS,
    choose_context,
    choose_machines,
    pair_frozen_predictions,
)
from factorygraph.training import verified_snapshots


def protocol_path(config: Phase2Config) -> Path:
    return (
        Path("docs/PHASE2_FULL_EXPERIMENT.md")
        if config.cohort_machines == 100
        else Path("docs/PHASE2_EXPERIMENT.md")
    )


def load_inputs(
    config: Phase2Config,
) -> tuple[ExperimentConfig, list[str], dict[str, pd.DataFrame], pd.DataFrame]:
    verify_artifacts(config.baseline_dir)
    baseline = ExperimentConfig.model_validate_json(
        (config.baseline_dir / "config.json").read_text()
    )
    for name in ["snapshot_manifest.json", "data_manifest.json"]:
        if sha256(config.baseline_dir / name) != sha256(baseline.processed_dir / name):
            raise ValueError(f"Prepared inputs differ from frozen Phase 1: {name}")
    snapshots = verified_snapshots(baseline)
    splits = chronological_split(snapshots, baseline.split)
    columns = json.loads((config.baseline_dir / "feature_contract.json").read_text())["columns"]
    for split in ["calibration", "validation", "test"]:
        frozen = pd.read_parquet(config.baseline_dir / f"{split}_predictions.parquet")
        paired = pair_frozen_predictions(splits[split], frozen)
        if len(paired) != len(frozen):
            raise ValueError(f"Full {split} membership differs from the Phase 1 saved population")
    failures = pd.read_parquet(config.baseline_dir / "evaluation_failures.parquet")
    return baseline, columns, splits, failures


def protected_hashes(config: Phase2Config) -> dict[str, str]:
    paths = [p for p in config.baseline_dir.iterdir() if p.is_file()]
    paths += list(Path("src/factorygraph").glob("*.py"))
    paths += [
        Path(p)
        for p in [
            "requirements.lock",
            "configs/baseline.yaml",
            "docs/PHASE1_REPORT.md",
            "docs/results/phase1.json",
        ]
    ]
    return {path.as_posix(): sha256(path) for path in sorted(paths)}


def register(config: Phase2Config) -> dict:
    if config.run_dir.exists() and any(config.run_dir.iterdir()):
        raise ValueError("Phase 2 run directory is nonempty; register a new run directory")
    baseline, columns, splits, _ = load_inputs(config)
    machines = choose_machines(
        sorted(splits["test"].machineID.unique().tolist()), config.cohort_machines, config.seed
    )
    config.run_dir.mkdir(parents=True, exist_ok=True)
    context_counts = {}
    for size in config.context_sizes:
        context = choose_context(splits["train"], size, config.seed)
        context[KEYS + ["label", "label_end"]].to_parquet(
            config.run_dir / f"context_{size}.parquet", index=False
        )
        context_counts[str(size)] = {
            "positive_rows": int(context.label.sum()),
            "latest_label_end": context.label_end.max().isoformat(),
        }
    query_counts = {}
    for split in ["validation", "test"]:
        cohort = splits[split].loc[splits[split].machineID.isin(machines)]
        cohort[KEYS].to_parquet(config.run_dir / f"{split}_queries.parquet", index=False)
        query_counts[split] = len(cohort)
    registration = {
        "config": config.model_dump(mode="json"),
        "machines": machines,
        "feature_columns": columns,
        "context_summary": context_counts,
        "query_rows": query_counts,
        "full_fleet_rows": {name: len(splits[name]) for name in ["validation", "test"]},
        "phase1_config": baseline.model_dump(mode="json"),
        "protected_sha256": protected_hashes(config),
        "membership_sha256": {path.name: sha256(path) for path in config.run_dir.glob("*.parquet")},
        "protocol_sha256": sha256(protocol_path(config)),
        "status": "registered_before_smoke_or_comparison",
        "test_previously_observed": True,
    }
    write_json(config.run_dir / "registration.json", registration)
    return registration


def verify_registration(config: Phase2Config) -> dict:
    registration = json.loads((config.run_dir / "registration.json").read_text())
    if registration["config"] != config.model_dump(mode="json"):
        raise ValueError("Configuration differs from the registered experiment")
    if registration["protected_sha256"] != protected_hashes(config):
        raise ValueError("Protected Phase 1 inputs changed after registration")
    if registration["protocol_sha256"] != sha256(protocol_path(config)):
        raise ValueError("Registered experiment protocol changed")
    for name, expected in registration["membership_sha256"].items():
        if sha256(config.run_dir / name) != expected:
            raise ValueError(f"Registered query/context membership changed: {name}")
    return registration


def registered_queries(config: Phase2Config, frame: pd.DataFrame, split: str) -> pd.DataFrame:
    keys = pd.read_parquet(config.run_dir / f"{split}_queries.parquet")
    query = keys.merge(frame, on=KEYS, how="left", validate="one_to_one", indicator=True)
    if not (query["_merge"] == "both").all():
        raise ValueError("Registered query membership cannot be recovered")
    return query.drop(columns="_merge")


def registered_context(config: Phase2Config, train: pd.DataFrame, size: int) -> pd.DataFrame:
    keys = pd.read_parquet(config.run_dir / f"context_{size}.parquet")
    context = keys[KEYS].merge(train, on=KEYS, how="left", validate="one_to_one")
    if not context["label"].equals(keys["label"]) or not context.label_end.equals(keys.label_end):
        raise ValueError("Registered context labels differ from frozen training labels")
    return context
