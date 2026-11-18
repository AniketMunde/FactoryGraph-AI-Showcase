import numpy as np
import pandas as pd

from factorygraph.phase2.metrics import complete_window_failures, summarize_timings


def test_event_metrics_require_every_opportunity_in_the_window():
    times = pd.date_range("2015-10-01", periods=8, freq="3h", tz="UTC")
    query = pd.DataFrame({"machineID": [1] * 8, "datetime": times})
    failures = pd.DataFrame({"machineID": [1], "datetime": [times[0] + pd.Timedelta(hours=24)]})
    selected, coverage = complete_window_failures(query, failures, 24, 3)
    assert len(selected) == 1
    assert coverage["events_with_complete_window"] == 1
    selected, coverage = complete_window_failures(query.iloc[1:], failures, 24, 3)
    assert selected.empty
    assert coverage["events_excluded_incomplete_window"] == 1


def test_latency_summary_uses_actual_rows_and_end_to_end_time():
    result = summarize_timings(
        [
            {"rows": 64, "total_seconds": 0.2, "sdk_predict_seconds": 0.15},
            {"rows": 10, "total_seconds": 0.1, "sdk_predict_seconds": 0.05},
        ]
    )
    assert result["rows"] == 74
    assert np.isclose(result["rows_per_second_total"], 74 / 0.3)
