import numpy as np
import pandas as pd
import pytest

from factorygraph.config import FeatureConfig, SplitConfig
from factorygraph.data import SENSORS
from factorygraph.features import (
    attach_labels,
    build_features,
    chronological_split,
    feature_columns,
)


def test_half_open_windows_and_strict_temporal_join(tables):
    config = FeatureConfig(windows_hours=[3], snapshot_hours=1)
    frame = build_features(tables, config)
    row = frame[(frame.machineID == 1) & (frame.datetime == pd.Timestamp("2015-01-01T03:00Z"))]
    assert row.volt_mean_3h.item() == 101  # 100,101,102; excludes current 103
    assert row.error1_count_3h.item() == 1  # excludes error at 03:00
    assert row.comp1_hours_since_maint.item() == 3  # excludes replacement at 03:00
    assert np.isnan(row.comp2_hours_since_maint.item())
    later = frame[(frame.machineID == 1) & (frame.datetime == pd.Timestamp("2015-01-01T04:00Z"))]
    assert later.error1_count_3h.item() == 2  # includes the lower boundary at 01:00
    assert later.comp1_hours_since_maint.item() == 1
    assert not set(["label", "next_failure", "machineID", "datetime"]) & set(
        feature_columns(config)
    )


def test_future_perturbations_do_not_change_features(tables):
    config = FeatureConfig(windows_hours=[3, 24], snapshot_hours=3)
    cutoff = pd.Timestamp("2015-01-06T12:00Z")
    before = build_features(tables, config).query("datetime <= @cutoff").reset_index(drop=True)
    altered = {name: df.copy() for name, df in tables.items()}
    altered["telemetry"].loc[altered["telemetry"].datetime >= cutoff, SENSORS] = 999999.0
    for name in ["errors", "maint"]:
        extra = altered[name].iloc[:1].copy()
        extra["datetime"] = cutoff
        altered[name] = pd.concat([altered[name], extra], ignore_index=True)
    altered["failures"] = altered["failures"].iloc[:0]  # labels never enter feature construction
    after = build_features(altered, config).query("datetime <= @cutoff").reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


def test_time_windows_do_not_bridge_gaps_or_machines(tables):
    tables["telemetry"] = tables["telemetry"].loc[
        ~(
            (tables["telemetry"].machineID == 1)
            & (tables["telemetry"].datetime == pd.Timestamp("2015-01-01T02:00Z"))
        )
    ]
    features = build_features(tables, FeatureConfig(windows_hours=[3], snapshot_hours=1))
    row = features[
        (features.machineID == 1) & (features.datetime == pd.Timestamp("2015-01-01T03:00Z"))
    ]
    assert row.volt_count_3h.item() == 2
    assert row.volt_mean_3h.item() == 100.5


def test_empty_window_retains_unknown_mean_and_zero_count(tables):
    cutoff = pd.Timestamp("2015-01-02T00:00Z")
    tables["telemetry"] = tables["telemetry"].loc[
        (tables["telemetry"].datetime < cutoff - pd.Timedelta(hours=5))
        | (tables["telemetry"].datetime >= cutoff)
    ]
    features = build_features(tables, FeatureConfig(windows_hours=[3], snapshot_hours=1))
    row = features[(features.machineID == 1) & (features.datetime == cutoff)]
    assert row.volt_count_3h.item() == 0
    assert np.isnan(row.volt_mean_3h.item())


def test_labels_horizon_boundary_simultaneous_events_and_censoring(tables):
    failure = pd.Timestamp("2015-01-02T00:00Z")
    tables["failures"] = tables["failures"].iloc[:1].copy()
    features = pd.DataFrame(
        {
            "machineID": [1] * 5,
            "datetime": [
                failure - pd.Timedelta(hours=24),
                failure - pd.Timedelta(hours=25),
                failure,
                failure + pd.Timedelta(hours=1),
                pd.Timestamp("2015-01-16T23:00Z"),
            ],
        }
    )
    labeled = attach_labels(features, tables, 24)
    assert labeled.label.tolist() == [1, 0, 0]
    assert failure not in labeled.datetime.tolist()
    assert labeled.datetime.max() < pd.Timestamp("2015-01-16T23:00Z")


def test_split_purges_prediction_windows(tables):
    config = SplitConfig(
        start="2015-01-01T00:00Z",
        train_end="2015-01-05T00:00Z",
        calibration_end="2015-01-08T00:00Z",
        validation_end="2015-01-11T00:00Z",
        test_end="2015-01-17T00:00Z",
    )
    frame = attach_labels(build_features(tables, FeatureConfig(windows_hours=[3])), tables, 24)
    splits = chronological_split(frame, config)
    ends = [config.train_end, config.calibration_end, config.validation_end, config.test_end]
    starts = [config.start, config.train_end, config.calibration_end, config.validation_end]
    for (name, split), start, end in zip(splits.items(), starts, ends, strict=True):
        assert len(split), name
        assert (split.datetime >= pd.Timestamp(start)).all()
        assert (split.label_end < pd.Timestamp(end)).all()
    all_keys = pd.concat(splits.values())[["machineID", "datetime"]]
    assert not all_keys.duplicated().any()


def test_split_config_requires_ordered_zoned_times():
    with pytest.raises(ValueError):
        SplitConfig(
            start="2015-01-01",
            train_end="2015-01-02",
            calibration_end="2015-01-03",
            validation_end="2015-01-04",
            test_end="2015-01-05",
        )
