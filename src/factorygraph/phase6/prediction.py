"""Approved saved predictions and unchanged split-scoped cooldown semantics."""

import numpy as np
import pandas as pd

from factorygraph.data import SOURCE_REVISION
from factorygraph.evaluation import alert_episodes, budget_threshold
from factorygraph.inference import calibrate
from factorygraph.phase6.common import KEYS, digest, iso, read_json
from factorygraph.phase6.integrity import A0, BASELINE
from factorygraph.phase6.schema import AlertPolicy, Prediction

DATASET_ID = f"microsoft-azure-synthetic:{SOURCE_REVISION}"


class PredictionReader:
    def __init__(self, registry):
        self.error = None
        self.frame = None
        self.registry = registry
        try:
            self._load()
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "approved_prediction_integrity_unavailable"

    def _load(self):
        r = self.registry
        for directory in [BASELINE, A0]:
            manifest = read_json(directory / "artifact_manifest.json")
            r.require(directory / "artifact_manifest.json")
            for filename in [
                "model.txt",
                "calibration.json",
                "policy.json",
                "feature_contract.json",
                "calibration_predictions.parquet",
                "validation_predictions.parquet",
                "test_predictions.parquet",
            ]:
                actual = r.require(directory / filename)
                if manifest.get(filename) != actual:
                    raise ValueError("Invalid model/prediction manifest")
        self.calibration = read_json(BASELINE / "calibration.json")
        if self.calibration != read_json(A0 / "calibration.json"):
            raise ValueError("Invalid calibration identity")
        self.policy = read_json(BASELINE / "policy.json")
        reproduced = read_json(A0 / "policy.json")
        contract = read_json(BASELINE / "feature_contract.json")
        if (
            self.policy["selected_on"] != "validation"
            or self.policy["cooldown_hours"] != 24
            or self.policy["budget_fraction"] != 0.01
            or contract["features"]["horizon_hours"] != 24
            or self.policy["threshold"] != reproduced["threshold"]
        ):
            raise ValueError("Unapproved policy")
        for split in ["calibration", "validation", "test"]:
            filename = f"{split}_predictions.parquet"
            left = pd.read_parquet(
                BASELINE / filename, columns=[*KEYS, "probability", "raw_probability"]
            )
            right = pd.read_parquet(
                A0 / filename, columns=[*KEYS, "probability", "raw_probability"]
            )
            if not left.equals(right) or left.duplicated(KEYS).any():
                raise ValueError("A0 prediction parity failure")
            if not np.isfinite(left.probability).all() or not left.probability.between(0, 1).all():
                raise ValueError("Malformed probability")
            if not np.array_equal(
                calibrate(left.raw_probability.to_numpy(), self.calibration),
                left.probability.to_numpy(),
            ):
                raise ValueError("Calibration does not reproduce predictions")
            if (
                split == "validation"
                and budget_threshold(left.probability.to_numpy(), 0.01) != self.policy["threshold"]
            ):
                raise ValueError("Frozen policy does not match accepted validation")
            if split == "test":
                self.frame = left.drop(columns="raw_probability").copy()
        self.index = self.frame.set_index(KEYS, verify_integrity=True)

    def get(self, machine, snapshot):
        if self.error:
            return Prediction(status="unavailable", reason=self.error)
        key = (machine, snapshot)
        if key not in self.index.index:
            return Prediction(status="unavailable", reason="unsupported_accepted_test_snapshot")
        r = self.registry
        return Prediction(
            status="verified",
            machine_id=machine,
            snapshot=iso(snapshot),
            probability=float(self.index.loc[key, "probability"]),
            model_id="approved-phase1-calibrated-lightgbm",
            model_sha256=r.require(BASELINE / "model.txt"),
            calibration_sha256=r.require(BASELINE / "calibration.json"),
            prediction_file_sha256=r.require(BASELINE / "test_predictions.parquet"),
            policy_sha256=r.require(BASELINE / "policy.json"),
            dataset_id=DATASET_ID,
            record_id="prediction:"
            + digest([machine, iso(snapshot), r.require(BASELINE / "test_predictions.parquet")]),
        )


class PolicyEvaluator:
    def __init__(self, reader):
        self.reader = reader
        self.rows = {}
        if reader.error or reader.frame is None:
            return
        self.rows = self.evaluate_rows(reader.frame, reader.policy["threshold"])

    @staticmethod
    def evaluate_rows(frame, threshold):
        episodes = alert_episodes(frame, threshold, 24)
        episode_keys = set(episodes[KEYS].itertuples(index=False, name=None))
        result = {}
        for machine, group in frame.sort_values(KEYS).groupby("machineID", sort=True):
            last = None
            for row in group.itertuples(index=False):
                key = (int(machine), row.datetime)
                high = bool(row.probability >= threshold)
                new = key in episode_keys
                if new:
                    last = row.datetime
                result[key] = {
                    "above_threshold": high,
                    "new_alert": new,
                    "cooldown_suppressed": high and not new,
                    "last_episode_timestamp": iso(last),
                }
        return result

    def get(self, prediction):
        if prediction.status != "verified":
            return AlertPolicy(status="unavailable")
        key = (prediction.machine_id, pd.Timestamp(prediction.snapshot))
        return AlertPolicy(
            status="verified",
            threshold=self.reader.policy["threshold"],
            policy_sha256=prediction.policy_sha256,
            record_id="policy:" + digest([prediction.record_id, prediction.policy_sha256]),
            **self.rows[key],
        )
