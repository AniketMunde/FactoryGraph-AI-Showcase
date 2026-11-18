import numpy as np
import pandas as pd
import pytest

from factorygraph.evaluation import alert_episodes, budget_threshold, evaluate_predictions


@pytest.mark.parametrize(
    "probabilities,budget,expected",
    [
        ([0.1, 0.2, 0.3, 0.4], 0.25, 1),
        ([0.5] * 4, 0.5, 0),
        ([0.1, 0.2], 0.01, 0),
    ],
)
def test_budget_ties_and_zero_capacity(probabilities, budget, expected):
    p = np.array(probabilities)
    threshold = budget_threshold(p, budget)
    assert (p >= threshold).sum() == expected


def test_metrics_and_episode_cooldown():
    times = pd.date_range("2015-01-01", periods=4, freq="3h", tz="UTC")
    predictions = pd.DataFrame(
        {
            "machineID": [1] * 4,
            "datetime": times,
            "label": [0, 1, 1, 0],
            "probability": [0.9, 0.8, 0.7, 0.1],
        }
    )
    failures = pd.DataFrame({"machineID": [1], "datetime": [times[2] + pd.Timedelta(hours=1)]})
    metrics = evaluate_predictions(
        predictions,
        failures,
        threshold=0.75,
        budget_fraction=0.25,
        snapshot_hours=3,
        horizon_hours=4,
        cooldown_hours=3,
    )
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["false_episodes_per_machine_day"] == 2.0
    assert metrics["event_recall"] == 1.0
    assert metrics["lead_time_hours_median_detected"] == 4.0
    assert len(alert_episodes(predictions, 0.75, 24)) == 1


def test_single_class_metrics_are_explicitly_undefined():
    predictions = pd.DataFrame(
        {
            "machineID": [1],
            "datetime": [pd.Timestamp("2015-01-01T00:00Z")],
            "label": [0],
            "probability": [0.1],
        }
    )
    failures = pd.DataFrame({"machineID": [], "datetime": pd.to_datetime([], utc=True)})
    metrics = evaluate_predictions(
        predictions,
        failures,
        threshold=0.5,
        budget_fraction=0.1,
        snapshot_hours=3,
        horizon_hours=24,
        cooldown_hours=24,
    )
    assert metrics["roc_auc"] is None
    assert metrics["pr_auc_average_precision"] is None
    assert metrics["event_recall"] is None
