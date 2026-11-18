import numpy as np
import pandas as pd
import pytest

from factorygraph.phase3.anomaly import fit_thresholds, residual_scores, robust_observation_scores
from factorygraph.phase3.sequences import sequence_map


def test_robust_scores_are_historical_and_do_not_use_failure_labels():
    times = pd.date_range("2015-01-01", periods=100, freq="h", tz="UTC")
    data = pd.DataFrame({"machineID": 1, "datetime": times, "volt": np.arange(100, dtype=float)})
    first = robust_observation_scores(sequence_map(data, ["volt"]), times[24], times[80], 24)
    data.loc[data.datetime > times[48], "volt"] = 999999
    second = robust_observation_scores(sequence_map(data, ["volt"]), times[24], times[80], 24)
    pd.testing.assert_frame_equal(
        first.loc[first.observation_time <= times[48]],
        second.loc[second.observation_time <= times[48]],
    )
    assert np.isclose(first.score.iloc[0], 12.5 / (6 * 1.4826))


def test_future_forecast_targets_cannot_enter_current_residual():
    issue = pd.Timestamp("2015-01-02T00:00Z")
    evaluation = pd.DataFrame(
        {
            "machineID": [1, 1],
            "channel": ["volt"] * 2,
            "issue_time": [issue] * 2,
            "source_observation_time": [issue - pd.Timedelta(hours=1)] * 2,
            "target_time": [issue, issue + pd.Timedelta(hours=24)],
            "actual": [5.0, 99999.0],
            "chronos": [3.0, 0.0],
            "context_robust_scale": [2.0, 2.0],
        }
    )
    scores = residual_scores(evaluation, issue)
    assert len(scores) == 1 and scores.score.item() == 1
    assert scores.observation_time.item() == issue


def test_test_data_cannot_fit_thresholds():
    start, end = pd.Timestamp("2015-09-01T00:00Z"), pd.Timestamp("2015-10-01T00:00Z")
    scores = pd.DataFrame(
        {
            "method": ["robust_mad"],
            "channel": ["volt"],
            "score": [3.0],
            "observation_time": [end],
            "source_max": [end],
        }
    )
    with pytest.raises(ValueError, match="validation"):
        fit_thresholds(scores, start, end)
    scores["observation_time"] = start
    scores["source_max"] = start
    assert fit_thresholds(scores, start, end)["thresholds"]["robust_mad:volt"] == 3
