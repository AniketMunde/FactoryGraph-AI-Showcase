import numpy as np
import pandas as pd
import pytest

from factorygraph.phase3.config import Phase3Config
from factorygraph.phase3.export import build_export, save_export
from factorygraph.phase3.sequences import Window
from factorygraph.phase3.study import forecast_table


def test_export_snapshot_alignment_provenance_and_future_perturbation(tmp_path):
    issue = pd.Timestamp("2015-10-01T00:00Z")
    snapshot = issue + pd.Timedelta(hours=3)
    config = Phase3Config(run_dir=tmp_path, channels=["volt"], context_length=24)
    window = Window(1, issue, issue - pd.Timedelta(hours=1), ["volt"], np.ones((1, 24)))
    q = np.tile(np.array([0.5, 1, 1.5]), (1, 1, 24, 1))
    forecasts = forecast_table([window], q, 24)
    times = pd.date_range(issue - pd.Timedelta(hours=24), issue + pd.Timedelta(hours=24), freq="h")
    frames = []
    for method in ["robust_mad", "forecast_residual"]:
        frames.append(
            pd.DataFrame(
                {
                    "machineID": 1,
                    "channel": "volt",
                    "method": method,
                    "observation_time": times,
                    "source_max": times,
                    "score": np.arange(len(times), dtype=float),
                }
            )
        )
    scores = pd.concat(frames, ignore_index=True)
    thresholds = {
        "fit_end_exclusive": issue.isoformat(),
        "source_max": (issue - pd.Timedelta(hours=1)).isoformat(),
        "thresholds": {"robust_mad:volt": 20, "forecast_residual:volt": 20},
    }
    snapshots = pd.DataFrame({"machineID": [1], "datetime": [snapshot]})
    original = build_export(snapshots, forecasts, scores, thresholds, config)
    scores.loc[scores.observation_time >= snapshot, "score"] = 999999
    changed = build_export(snapshots, forecasts, scores, thresholds, config)
    pd.testing.assert_frame_equal(original, changed)
    assert original.p3_volt_forecast_residual_latest.item() == 26
    assert original.latest_residual_observation_timestamp.item() == snapshot - pd.Timedelta(hours=1)
    assert original.forecast_issue_timestamp.item() == issue
    assert original.forecast_age_hours.item() == 3
    manifest = save_export(original, config)
    assert manifest["rows"] == 1
    assert "model_id" not in manifest["feature_columns"]
    assert all(
        pd.api.types.is_numeric_dtype(original[name]) for name in manifest["feature_columns"]
    )
    with pytest.raises(ValueError, match="thresholds"):
        build_export(
            snapshots.assign(datetime=issue - pd.Timedelta(hours=3)),
            forecasts,
            scores,
            thresholds,
            config,
        )
