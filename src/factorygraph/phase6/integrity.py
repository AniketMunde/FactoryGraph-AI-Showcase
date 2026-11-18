"""Gates A/B: accepted-input verification, preservation and label-free registration."""

from pathlib import Path

import pandas as pd

from factorygraph.io import sha256
from factorygraph.phase5.common import verify_prior
from factorygraph.phase6.common import KEYS, POLICIES, digest, iso, read_json, save_new

BASELINE = Path("artifacts/baseline")
A0 = Path("artifacts/phase5/study/models/A0")
P5 = Path("artifacts/phase5/study")


def verify_mapping(root, mapping):
    for name, expected in mapping.items():
        if sha256(Path(root) / name) != expected:
            raise ValueError(f"Integrity mismatch: {Path(root) / name}")


def prediction_parity():
    result = {}
    for split in ["calibration", "validation", "test"]:
        filename = f"{split}_predictions.parquet"
        columns = [*KEYS, "probability"]
        left = pd.read_parquet(BASELINE / filename, columns=columns)
        right = pd.read_parquet(A0 / filename, columns=columns)
        if not left.equals(right):
            raise ValueError("Approved baseline and Phase 5 A0 identity differ")
        result[split] = {"rows": len(left), "maximum_probability_difference": 0.0}
    if read_json(BASELINE / "calibration.json") != read_json(A0 / "calibration.json"):
        raise ValueError("Calibration identity differs")
    old, reproduced = read_json(BASELINE / "policy.json"), read_json(A0 / "policy.json")
    if old["threshold"] != reproduced["threshold"] or reproduced["cooldown_hours"] != 24:
        raise ValueError("Policy identity differs")
    return result


def protect(config):
    root = config.run_dir
    if (root / "gate_a.json").exists():
        raise ValueError("Gate A exists; choose a fresh run directory")
    previous_count = verify_prior()
    for name in [
        "baseline",
        "phase2/kumo-full",
        "phase3/azure",
        "phase3/metropt",
        "phase4",
        "phase5",
    ]:
        directory = Path("artifacts") / name
        verify_mapping(directory, read_json(directory / "artifact_manifest.json"))
    p5 = read_json("docs/results/phase5.json")
    for field in ["source_sha256", "implementation_sha256"]:
        verify_mapping(Path("."), p5[field])
    parity = prediction_parity()
    paths = set()
    for prefix in [
        "artifacts/baseline",
        "artifacts/phase2",
        "artifacts/phase3",
        "artifacts/phase4",
        "artifacts/phase5",
        "data/raw/azure",
        "data/processed/azure",
        "data/models",
        "data/phase3",
        "src/factorygraph",
        "tests",
        "configs",
        "requirements",
        "docs",
    ]:
        paths.update(
            p
            for p in Path(prefix).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and "phase6" not in p.parts
            and "phase6" not in p.name.lower()
            and p.name not in {"ARCHITECTURE.md", "ROADMAP.md", "DECISIONS.md"}
        )
    paths.update([Path("requirements.lock"), Path("pyproject.toml"), Path("MANIFEST.in")])
    protected = {p.as_posix(): sha256(p) for p in sorted(paths)}
    save_new(root / "protected.json", protected)
    result = {
        "status": "passed",
        "previous_protected_files": previous_count,
        "protected_files": len(protected),
        "baseline_A0_parity": parity,
    }
    save_new(root / "gate_a.json", result)
    return result


def verify_protected(config):
    protected = read_json(config.run_dir / "protected.json")
    verify_mapping(Path("."), protected)
    return len(protected)


def input_paths():
    paths = [
        BASELINE / "artifact_manifest.json",
        A0 / "artifact_manifest.json",
        BASELINE / "model.txt",
        BASELINE / "calibration.json",
        BASELINE / "feature_contract.json",
        BASELINE / "policy.json",
        BASELINE / "data_manifest.json",
        BASELINE / "snapshot_manifest.json",
        Path("data/processed/azure/snapshots.parquet"),
        Path("data/raw/azure/source_manifest.json"),
        Path("artifacts/phase4/full/build.json"),
        Path("artifacts/phase4/full/registration.json"),
        Path("configs/phase4/full.yaml"),
        P5 / "temporal_manifest.json",
    ]
    paths.extend(
        Path("data/raw/azure") / f"PdM_{n}.csv"
        for n in ["machines", "telemetry", "errors", "maint", "failures"]
    )
    for split in ["calibration", "validation", "test"]:
        paths.extend(
            [BASELINE / f"{split}_predictions.parquet", A0 / f"{split}_predictions.parquet"]
        )
    paths.extend(
        A0 / n for n in ["model.txt", "calibration.json", "policy.json", "feature_contract.json"]
    )
    for split in ["train", "calibration", "validation", "test"]:
        paths.extend([P5 / f"keys_{split}.parquet", P5 / f"temporal_c_{split}.parquet"])
    return paths


def select_cases(config):
    # No future labels are loaded. Selection identities are frozen before service execution.
    from factorygraph.evaluation import alert_episodes

    p = pd.read_parquet(BASELINE / "test_predictions.parquet", columns=[*KEYS, "probability"])
    policy = read_json(BASELINE / "policy.json")
    ep = alert_episodes(p, policy["threshold"], 24)
    candidates = []

    def add(machine, time, category):
        key = (int(machine), iso(time))
        if not any((r["machine_id"], r["snapshot"]) == key for r in candidates):
            candidates.append({"machine_id": key[0], "snapshot": key[1], "category": category})

    categories = {
        "new_alert": ep,
        "cooldown": p.loc[(p.probability >= policy["threshold"]) & ~p.index.isin(ep.index)],
        "non_alert": p.loc[p.probability < policy["threshold"]],
    }
    for kind, frame in categories.items():
        for r in frame.head(8).itertuples():
            add(r.machineID, r.datetime, kind)
    for machine in [1, 17, 42]:
        for time in ["2015-10-15T00:00Z", "2015-11-15T00:00Z"]:
            add(machine, time, "fixed_context")
    events = []
    for name in ["errors", "maint", "failures"]:
        f = pd.read_csv(f"data/raw/azure/PdM_{name}.csv")
        f["datetime"] = pd.to_datetime(f.datetime, utc=True)
        events.append(f[[*KEYS]])
        selected = (
            f.loc[
                (f.datetime >= pd.Timestamp("2015-10-01T00:00Z"))
                & (f.datetime < pd.Timestamp("2015-11-01T00:00Z"))
            ]
            .sort_values(KEYS)
            .head(4)
        )
        for r in selected.itertuples():
            add(r.machineID, r.datetime, f"boundary_{name}")
            add(r.machineID, r.datetime + pd.Timedelta(hours=1), f"after_{name}")
    all_events = pd.concat(events)
    counts = (
        all_events.loc[all_events.datetime < pd.Timestamp("2015-10-15T00:00Z")]
        .groupby("machineID")
        .size()
        .reindex(range(1, 101), fill_value=0)
    )
    add(counts.idxmin(), "2015-10-15T00:00Z", "sparse_history")
    add(counts.idxmax(), "2015-10-15T00:00Z", "extensive_history")
    early = pd.read_parquet(
        P5 / "temporal_c_train.parquet", columns=[*KEYS, "p5_c_forecast_available"]
    )
    for r in early.loc[early.p5_c_forecast_available == 0].head(3).itertuples():
        add(r.machineID, r.datetime, "missing_forecast")
    failures = pd.read_csv("data/raw/azure/PdM_failures.csv")
    maint = pd.read_csv("data/raw/azure/PdM_maint.csv")
    overlap = failures.merge(maint, left_on=[*KEYS, "failure"], right_on=[*KEYS, "comp"])
    for r in overlap.head(2).itertuples():
        add(r.machineID, pd.Timestamp(r.datetime, tz="UTC"), "overlap_cutoff")
        add(
            r.machineID,
            pd.Timestamp(r.datetime, tz="UTC") + pd.Timedelta(hours=3),
            "overlap_visible",
        )
    add(10001, "2015-10-15T00:00Z", "unknown_machine")
    add(17, "2015-10-15T00:01Z", "unsupported_time")
    return candidates


def register(config):
    config.check()
    if not (config.run_dir / "gate_a.json").exists():
        raise ValueError("Gate A must pass first")
    verify_protected(config)
    policies = {p: sha256(Path(p)) for p in POLICIES}
    inputs = {p.as_posix(): sha256(p) for p in input_paths()}
    cases = select_cases(config)
    record = {
        "version": config.version,
        "config": config.model_dump(mode="json"),
        "policies_sha256": policies,
        "inputs_sha256": inputs,
        "cases": cases,
        "case_selection": "Deterministic label-free protocol v1",
        "baseline_A0_parity": prediction_parity(),
        "registered_before_case_study": True,
    }
    save_new(config.run_dir / "registration.json", record)
    return {"status": "registered", "cases": len(cases), "registration_sha256": digest(record)}


class ArtifactRegistry:
    def __init__(self, config):
        self.config = config.check()
        self.record = read_json(config.run_dir / "registration.json")
        if self.record["config"] != config.model_dump(mode="json"):
            raise ValueError("Unrecognized registered configuration")
        verify_mapping(Path("."), self.record["policies_sha256"])
        self.hashes = self.record["inputs_sha256"]
        self.checked = set()

    def require(self, path):
        name = Path(path).as_posix()
        if name not in self.hashes:
            raise ValueError("Artifact has no registered provenance")
        if name not in self.checked:
            if sha256(Path(path)) != self.hashes[name]:
                raise ValueError("Registered artifact hash mismatch")
            self.checked.add(name)
        return self.hashes[name]
