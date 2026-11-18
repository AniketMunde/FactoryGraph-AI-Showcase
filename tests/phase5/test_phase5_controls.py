import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from factorygraph.phase5.analysis import event_outcomes, metrics, weighted_ap
from factorygraph.phase5.common import GROUPS, exact_join
from factorygraph.phase5.learning import columns_for, fit_calibrator, validation_policies
from factorygraph.phase5.relational import compute, past_counts


def test_independent_relational_counts_and_future_peer_exclusion(tables):
    tables["machines"]["model"] = "model1"
    cutoff = pd.Timestamp("2015-01-04T00:00Z")
    keys = pd.DataFrame({"machineID": [2, 1], "datetime": [cutoff, cutoff]})
    result = compute(keys, tables)
    changed = {n: f.copy() for n, f in tables.items()}
    changed["failures"] = pd.concat(
        [
            changed["failures"],
            pd.DataFrame(
                {
                    "datetime": [cutoff, cutoff + pd.Timedelta(hours=1)],
                    "machineID": [1, 2],
                    "failure": ["comp4", "comp4"],
                }
            ),
        ]
    )
    after = compute(keys, changed)
    pd.testing.assert_frame_equal(result, after)
    assert result.machineID.tolist() == [2, 1]
    assert result.g4_errors_records_total.tolist() == [1, 2]
    assert result.g4_model_peer_failures_records_30d.tolist() == [2, 2]
    times = pd.Series(pd.to_datetime(["2015-01-01T00:00Z"] * 2))
    assert past_counts(times, pd.DatetimeIndex([pd.Timestamp("2015-01-01T00:00Z")])).item() == 0


def test_exact_join_order_and_identical_population():
    keys = pd.DataFrame(
        {"machineID": [2, 1], "datetime": pd.to_datetime(["2015-01-01T00:00Z"] * 2)}
    )
    right = keys.iloc[::-1].assign(value=[10, 20])
    out = exact_join(keys, right, ["value"])
    assert out.value.tolist() == [20, 10]
    with pytest.raises(ValueError):
        exact_join(keys, right.head(1), ["value"])


def test_calibration_and_alert_chronology_isolated():
    raw = np.array([0.01, 0.05, 0.8, 0.9])
    labels = np.array([0, 0, 1, 1])
    cal = pd.Series(pd.date_range("2015-08-01T00:00Z", periods=4, freq="D"))
    parameters = fit_calibrator(raw, labels, cal)
    assert np.isfinite(list(parameters.values())).all()
    with pytest.raises(ValueError, match="August"):
        fit_calibrator(raw, labels, cal + pd.Timedelta(days=61))
    times = pd.Series(pd.date_range("2015-09-01T00:00Z", periods=100, freq="h"))
    probabilities = np.linspace(0, 1, 100)
    policy = validation_policies(probabilities, times, [0.01], 0.9)
    assert (probabilities >= policy["budget_0.01"]).sum() <= 1
    with pytest.raises(ValueError, match="September"):
        validation_policies(probabilities, times + pd.Timedelta(days=31), [0.01], 0.9)


def test_ablation_families_and_no_label_contract():
    groups = {"A": ["tabular"], "B": ["cheap"], "C": ["chronos"], "D": ["graph"], "E": ["graph"]}
    assert columns_for({"groups": groups}, "A6") == ["tabular", "chronos", "graph"]
    assert GROUPS["A4"] == ["A", "E"]
    assert columns_for({"groups": groups}, "A5") == ["tabular", "cheap", "graph"]
    groups["C"] = ["label"]
    with pytest.raises(ValueError, match="label-bearing"):
        columns_for({"groups": groups}, "A6")


@pytest.mark.parametrize("weights", [np.ones(6), np.array([0, 2, 1, 1, 3, 0])])
def test_weighted_ap_matches_independent_sklearn_with_ties(weights):
    y = np.array([0, 1, 0, 1, 1, 0])
    p = np.array([0.1, 0.8, 0.8, 0.6, 0.5, 0.2])
    assert weighted_ap(y, p, weights) == pytest.approx(
        average_precision_score(y, p, sample_weight=weights)
    )


def test_original_operational_event_identity_and_median_lead():
    times = pd.date_range("2015-10-01T00:00Z", periods=8, freq="3h")
    p = pd.DataFrame(
        {
            "machineID": 1,
            "datetime": times,
            "label": [1] * 8,
            "label_end": times + pd.Timedelta(hours=24),
            "probability": [0.9] + [0.1] * 7,
        }
    )
    failure = times[0] + pd.Timedelta(hours=24)
    f = pd.DataFrame(
        {"machineID": [1, 1], "datetime": [failure, failure], "failure": ["comp1", "comp2"]}
    )
    events = event_outcomes(p, f, 0.8)
    assert len(events) == 1 and events.detected.item()
    assert events.component_codes.item() == "comp1+comp2"
    actual = metrics(p, f, 0.8)
    assert actual["eligible_failure_events"] == 1
    assert actual["lead_time_hours_median_detected"] == 24


def test_analysis_requires_all_predictions_frozen(tmp_path):
    from factorygraph.phase5.analysis import analyze
    from factorygraph.phase5.common import Config

    with pytest.raises(ValueError, match="Freeze all models"):
        analyze(Config(run_dir=tmp_path))
