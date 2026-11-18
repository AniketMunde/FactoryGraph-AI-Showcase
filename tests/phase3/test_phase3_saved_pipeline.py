import numpy as np
import pandas as pd
import pytest

from factorygraph.io import sha256, write_json
from factorygraph.phase3.metrics import attach_actuals, summarize
from factorygraph.phase3.sequences import Window
from factorygraph.phase3.study import forecast_table, load_forecasts


def test_saved_forecast_roundtrip_metrics_and_integrity(tmp_path):
    """Software integration fixture only; no synthetic fixture is reported as model evidence."""
    issue = pd.Timestamp("2015-10-01T00:00Z")
    window = Window(3, issue, issue - pd.Timedelta(hours=1), ["volt"], np.ones((1, 24)))
    values = np.tile([0.0, 1.0, 2.0], (1, 1, 24, 1))
    forecasts = forecast_table([window], values, 24)
    forecasts.to_parquet(tmp_path / "batch.parquet", index=False)
    write_json(
        tmp_path / "manifest.json", {"files": {"batch.parquet": sha256(tmp_path / "batch.parquet")}}
    )
    frozen = load_forecasts(tmp_path)
    actual = pd.DataFrame(
        {
            "machineID": 3,
            "target_time": forecasts.target_time,
            "channel": "volt",
            "actual": np.full(24, 1.0),
        }
    )
    evaluated = attach_actuals(frozen, actual)
    scales = pd.DataFrame({"machineID": [3], "channel": ["volt"], "mase_scale": [1.0]})
    metrics = summarize(evaluated, scales)
    assert metrics["24"]["by_channel"]["volt"]["chronos"]["mae"] == 0
    assert metrics["24"]["by_channel"]["volt"]["chronos"]["interval_80_coverage"] == 1
    assert metrics["24"]["by_machine"]["3"]["chronos"] == 0
    (tmp_path / "batch.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        load_forecasts(tmp_path)
