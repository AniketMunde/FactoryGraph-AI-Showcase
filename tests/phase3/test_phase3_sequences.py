import numpy as np
import pandas as pd
import pytest

from factorygraph.phase3.metrics import attach_actuals, point_metrics
from factorygraph.phase3.sequences import (
    classical_forecasts,
    context_window,
    eligible_origins,
    robust_scale,
    sequence_map,
    training_scales,
    validate_telemetry,
)
from factorygraph.phase3.study import forecast_table


def telemetry():
    times = pd.date_range("2015-01-01", periods=240, freq="h", tz="UTC")
    return pd.DataFrame(
        {"machineID": 1, "datetime": times, "volt": np.arange(len(times), dtype=float)}
    )


def test_context_excludes_current_and_future_values_and_is_reproducible():
    data = telemetry()
    issue = data.datetime.iloc[72]
    original = context_window(1, sequence_map(data, ["volt"])[1], issue, 24)
    data.loc[data.datetime >= issue, "volt"] = 999999
    changed = context_window(1, sequence_map(data, ["volt"])[1], issue, 24)
    np.testing.assert_array_equal(original.values, changed.values)
    np.testing.assert_array_equal(original.values[0], np.arange(48, 72))
    assert original.source_max == issue - pd.Timedelta(hours=1)
    assert original.machine == 1
    np.testing.assert_array_equal(robust_scale(original.values)[1], robust_scale(changed.values)[1])


@pytest.mark.parametrize("case", ["duplicate", "missing", "off_grid", "infinite"])
def test_schema_and_gap_handling(case):
    data = telemetry()
    issue = data.datetime.iloc[72]
    if case == "duplicate":
        data = pd.concat([data, data.iloc[:1]])
        with pytest.raises(ValueError, match="Duplicate"):
            validate_telemetry(data, ["volt"])
    elif case == "infinite":
        data.loc[0, "volt"] = np.inf
        with pytest.raises(ValueError, match="Infinite"):
            validate_telemetry(data, ["volt"])
    else:
        if case == "missing":
            data = data.drop(index=60)
        else:
            data.loc[60, "datetime"] += pd.Timedelta(minutes=30)
        with pytest.raises(ValueError, match="Incomplete"):
            context_window(1, sequence_map(data, ["volt"])[1], issue, 24)


def test_ordering_and_complete_horizon_membership():
    data = telemetry()
    seq = sequence_map(data.sample(frac=1, random_state=42), ["volt"])
    assert seq[1].index.is_monotonic_increasing
    origins, excluded = eligible_origins(
        seq, pd.Timestamp("2015-01-03T00:00Z"), pd.Timestamp("2015-01-05T00:00Z"), 24, 24, 24
    )
    assert len(origins) == 2
    assert not any(excluded.values())
    seq[1] = seq[1].drop(pd.Timestamp("2015-01-04T23:00Z"))
    origins, excluded = eligible_origins(
        seq, pd.Timestamp("2015-01-03T00:00Z"), pd.Timestamp("2015-01-05T00:00Z"), 24, 24, 24
    )
    assert len(origins) == 1
    assert excluded["target"] == 1


def test_classical_baselines_use_only_given_history():
    values = np.arange(48, dtype=float).reshape(1, -1)
    output = classical_forecasts(values, 24)
    np.testing.assert_array_equal(output["persistence"], np.full((1, 24), 47))
    np.testing.assert_array_equal(output["seasonal_naive"], np.arange(24, 48).reshape(1, -1))
    assert output["rolling_mean"][0, 0] == 35.5


def test_training_only_mase_scale_and_known_metrics():
    data = telemetry()
    end = pd.Timestamp("2015-01-05T00:00Z")
    scales = training_scales(sequence_map(data, ["volt"]), end)
    data.loc[data.datetime >= end, "volt"] = 99999
    pd.testing.assert_frame_equal(scales, training_scales(sequence_map(data, ["volt"]), end))
    assert scales.mase_scale.item() == 24
    result = point_metrics(np.array([1, 2]), np.array([0, 3]), np.array([2, 2]))
    assert result["mae"] == result["rmse"] == 1
    assert result["mase"] == 0.5
    assert point_metrics(np.array([1]), np.array([0]), np.array([0]))["mase"] is None


def test_forecast_alignment_machine_identity_and_actual_join():
    seq = sequence_map(telemetry(), ["volt"])[1]
    issue = pd.Timestamp("2015-01-04T00:00Z")
    window = context_window(1, seq, issue, 24)
    q = np.full((1, 1, 24, 3), 0.0)
    forecasts = forecast_table([window], q, 24)
    assert forecasts.target_time.min() == issue
    assert forecasts.lead.min() == 1 and forecasts.lead.max() == 24
    actual = pd.DataFrame(
        {"machineID": 1, "target_time": forecasts.target_time, "channel": "volt", "actual": 1.0}
    )
    assert len(attach_actuals(forecasts, actual)) == 24
    with pytest.raises(ValueError, match="matching"):
        attach_actuals(forecasts, actual.assign(machineID=2))
    with pytest.raises(ValueError, match="Duplicate"):
        attach_actuals(forecasts, pd.concat([actual, actual.iloc[:1]]))
