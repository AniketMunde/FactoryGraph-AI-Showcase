import numpy as np
import pandas as pd
import pytest

from factorygraph.phase3.sequences import context_window
from factorygraph.phase3.study import forecast_table
from factorygraph.phase5.common import Config, exact_join
from factorygraph.phase5.temporal import cheap_width, machine_features, origins_for


def fixture_forecast():
    config = Config()
    times = pd.date_range("2015-01-01T06:00Z", periods=24 * 12, freq="h")
    seq = pd.DataFrame(
        {
            c: np.arange(len(times), dtype=float) + 100
            for c in ["volt", "rotate", "pressure", "vibration"]
        },
        index=times,
    )
    issue = pd.Timestamp("2015-01-09T00:00Z")
    window = context_window(1, seq, issue, 168)
    q = np.tile([100.0, 110.0, 120.0], (1, 4, 24, 1))
    f = forecast_table([window], q, 24)
    f["cheap_interval_width"] = np.repeat(cheap_width(window.values), 24)
    return config, seq, f, issue


def test_historical_issue_context_and_warmup_without_target_selection():
    config, seq, f, issue = fixture_forecast()
    origins, excluded = origins_for({1: seq}, issue - pd.Timedelta(days=1), issue)
    assert excluded == 1 and origins.issue_time.tolist() == [issue]
    changed = seq.copy()
    changed.loc[changed.index >= issue, :] = np.nan
    second, _ = origins_for({1: changed}, issue - pd.Timedelta(days=1), issue)
    pd.testing.assert_frame_equal(origins, second)
    snapshots = pd.DataFrame(
        {"machineID": [1, 1], "datetime": [issue - pd.Timedelta(days=1), issue]}
    )
    out = machine_features(snapshots, f, seq, "c", config)
    assert out.p5_c_forecast_available.tolist() == [0, 1]
    assert pd.isna(out.p5_c_forecast_age_hours.iloc[0])
    assert out.p5_c_volt_residual_valid_count_24h.iloc[0] == 0
    assert pd.isna(out.p5_c_volt_forecast_mean.iloc[0])
    assert not any("anomaly_count" in c or "threshold" in c for c in out)


@pytest.mark.parametrize("prefix", ["b", "c"])
def test_matured_residual_and_future_perturbation(prefix):
    config, seq, f, issue = fixture_forecast()
    cutoff = issue + pd.Timedelta(hours=3)
    snapshots = pd.DataFrame({"machineID": [1], "datetime": [cutoff]})
    first = machine_features(snapshots, f, seq, prefix, config)
    changed = seq.copy()
    changed.loc[changed.index >= cutoff, :] = 999999
    second = machine_features(snapshots, f, changed, prefix, config)
    pd.testing.assert_frame_equal(first, second)
    assert first.latest_residual_observation_timestamp.item() == cutoff - pd.Timedelta(hours=1)
    assert first.forecast_issue_timestamp.item() == issue
    assert first[f"p5_{prefix}_volt_residual_valid_count_24h"].item() == 3
    assert first[f"p5_{prefix}_forecast_age_hours"].item() == 3
    assert len([c for c in first if c.startswith(f"p5_{prefix}_")]) == 40


def test_duplicate_keys_and_future_origin_rejected():
    key = pd.DataFrame({"machineID": [1], "datetime": [pd.Timestamp("2015-01-09T00:00Z")]})
    with pytest.raises(ValueError, match="Duplicate"):
        exact_join(pd.concat([key, key]), key, [])
    with pytest.raises(ValueError, match="populations"):
        exact_join(key, key.assign(machineID=2), [])
    config, seq, f, issue = fixture_forecast()
    f["source_observation_time"] = issue
    with pytest.raises(ValueError, match="Future context"):
        machine_features(key, f, seq, "c", config)


def test_cheap_width_uses_historical_errors():
    values = np.ones((4, 168)) * 10
    assert np.array_equal(cheap_width(values), np.zeros(4))


def test_no_forecast_history_preserves_missingness():
    config, seq, f, issue = fixture_forecast()
    keys = pd.DataFrame({"machineID": [1], "datetime": [issue - pd.Timedelta(days=1)]})
    result = machine_features(keys, f.iloc[:0], seq, "c", config)
    assert result.p5_c_forecast_available.item() == 0
    assert result.p5_c_volt_residual_valid_count_24h.item() == 0
    assert pd.isna(result.latest_source_observation_timestamp.item())


def test_frozen_forecast_tamper_rejected(tmp_path):
    from factorygraph.io import sha256, write_json
    from factorygraph.phase5.temporal import read_forecasts

    _, _, f, _ = fixture_forecast()
    target = tmp_path / "batch.parquet"
    f.to_parquet(target, index=False)
    write_json(tmp_path / "manifest.json", {"files": {"batch.parquet": sha256(target)}})
    assert len(next(read_forecasts(tmp_path))) == 96
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Frozen"):
        next(read_forecasts(tmp_path))
