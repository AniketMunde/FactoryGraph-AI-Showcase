"""Exact-key, label-free reads of accepted predictor inputs and supplementary context."""

from pathlib import Path

import numpy as np
import pandas as pd

from factorygraph.phase6.common import KEYS, digest, iso, read_json
from factorygraph.phase6.integrity import BASELINE, P5

REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"
POLICY_HASH = "fcc2d68c58ca3b32c3a5c61ea5d6f88f77694c298ecac70f8b9bf7a300b4911a"
CLOCKS = [
    "forecast_issue_timestamp",
    "latest_residual_observation_timestamp",
    "latest_source_observation_timestamp",
]


def numeric(values):
    result = {}
    for name, value in values.items():
        if pd.isna(value):
            result[name] = None
        elif np.isfinite(value):
            result[name] = float(value)
        else:
            raise ValueError("Nonfinite contextual value")
    return result


def validate_temporal(row, snapshot):
    issue, residual, source = [row[c] for c in CLOCKS]
    if any(pd.notna(v) and v >= snapshot for v in [source, residual]):
        raise ValueError("Future source/residual observation")
    if pd.notna(issue) and issue > snapshot:
        raise ValueError("Future forecast issue")
    available = int(row["p5_c_forecast_available"])
    if available not in [0, 1] or bool(available) != pd.notna(issue):
        raise ValueError("Conflicting forecast availability")
    if available and (pd.isna(source) or source < issue - pd.Timedelta(hours=1)):
        raise ValueError("Missing historical forecast source provenance")
    if (
        row["model_id"] != "amazon/chronos-2"
        or row["checkpoint_revision"] != REVISION
        or row["temporal_policy_sha256"] != POLICY_HASH
    ):
        raise ValueError("Temporal artifact identity conflict")


class TemporalContextReader:
    def __init__(self, registry):
        self.registry = registry
        self.error = None
        try:
            self._load()
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "historical_context_integrity_unavailable"

    def _load(self):
        r = self.registry
        self.columns = read_json(BASELINE / "feature_contract.json")["columns"]
        r.require(BASELINE / "feature_contract.json")
        self.snapshot_path = Path("data/processed/azure/snapshots.parquet")
        r.require(self.snapshot_path)
        self.inputs = pd.read_parquet(self.snapshot_path, columns=[*KEYS, *self.columns]).set_index(
            KEYS, verify_integrity=True
        )
        r.require(P5 / "temporal_manifest.json")
        manifest = read_json(P5 / "temporal_manifest.json")
        self.temporal_columns = manifest["groups"]["c"]["columns"]
        frames, keys = [], []
        for split, record in manifest["groups"]["c"]["splits"].items():
            path = P5 / f"temporal_c_{split}.parquet"
            if r.require(path) != record["sha256"]:
                raise ValueError("Temporal manifest mismatch")
            frame = pd.read_parquet(path)
            key_path = P5 / f"keys_{split}.parquet"
            r.require(key_path)
            membership = pd.read_parquet(key_path, columns=KEYS)
            if not frame[KEYS].equals(membership):
                raise ValueError("Context snapshot identity conflict")
            if np.isinf(frame[self.temporal_columns].to_numpy(dtype=float)).any():
                raise ValueError("Infinite context")
            frame["_path"] = path.as_posix()
            frames.append(frame)
            keys.append(membership)
        self.context = pd.concat(frames, ignore_index=True).set_index(KEYS, verify_integrity=True)
        self.accepted_keys = pd.concat(keys).set_index(KEYS, verify_integrity=True).index

    def get(self, machine, snapshot):
        unavailable = {
            "status": "unavailable",
            "reason": self.error or "unsupported_exact_snapshot",
        }
        if self.error or (machine, snapshot) not in self.accepted_keys:
            return unavailable
        key = (machine, snapshot)
        row = self.context.loc[key]
        try:
            validate_temporal(row, snapshot)
            actual = numeric(self.inputs.loc[key, self.columns].to_dict())
            supplementary = numeric(row[self.temporal_columns].to_dict())
        except (ValueError, KeyError, TypeError):
            return {"status": "unavailable", "reason": "context_clock_or_identity_invalid"}
        r = self.registry
        tabular_id = "feature:" + digest([machine, iso(snapshot), r.require(self.snapshot_path)])
        temporal_id = "temporal:" + digest([machine, iso(snapshot), r.require(row["_path"])])
        return {
            "status": "verified" if row.p5_c_forecast_available else "incomplete",
            "reason": None
            if row.p5_c_forecast_available
            else "insufficient_historical_forecast_context",
            "approved_predictor_inputs": {
                "record_id": tabular_id,
                "values": actual,
                "artifact_sha256": r.require(self.snapshot_path),
                "latest_source_observation_timestamp": iso(snapshot - pd.Timedelta(hours=1)),
                "source_clock_basis": "Accepted hourly cadence; strict historical windows",
                "availability": (
                    "Dynamic windows strictly before snapshot; metadata known at study start"
                ),
            },
            "supplementary_chronos_context": {
                "record_id": temporal_id,
                "values": supplementary,
                "artifact_path": row["_path"],
                "artifact_sha256": r.require(row["_path"]),
                "model_id": row.model_id,
                "checkpoint_revision": row.checkpoint_revision,
                "computation_policy_sha256": row.temporal_policy_sha256,
                **{c: iso(row[c]) for c in CLOCKS},
                "forecast_context_last_observation_timestamp": iso(
                    row.forecast_issue_timestamp - pd.Timedelta(hours=1)
                )
                if pd.notna(row.forecast_issue_timestamp)
                else None,
                "modifies_primary_probability": False,
                "interpretation": "Forecast outputs and matured historical residuals; no diagnosis",
            },
        }
