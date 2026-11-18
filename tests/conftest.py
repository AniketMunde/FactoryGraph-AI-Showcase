"""Small invented data for correctness tests only; never a benchmark fallback."""

import numpy as np
import pandas as pd
import pytest

from factorygraph.data import SENSORS, validate_tables


@pytest.fixture
def tables():
    times = pd.date_range("2015-01-01", periods=24 * 16, freq="h", tz="UTC")
    telemetry = pd.concat(
        [
            pd.DataFrame(
                {
                    "datetime": times,
                    "machineID": machine,
                    **{
                        sensor: np.arange(len(times), dtype=float) + machine * 100
                        for sensor in SENSORS
                    },
                }
            )
            for machine in [1, 2]
        ],
        ignore_index=True,
    )
    events = pd.date_range("2015-01-02", "2015-01-16", freq="36h", tz="UTC")
    return validate_tables(
        {
            "machines": pd.DataFrame(
                {"machineID": [1, 2], "model": ["model1", "model2"], "age": [5, 10]}
            ),
            "telemetry": telemetry,
            "errors": pd.DataFrame(
                {
                    "datetime": [times[1], times[3], times[4]],
                    "machineID": [1, 1, 2],
                    "errorID": ["error1"] * 3,
                }
            ),
            "maint": pd.DataFrame(
                {"datetime": [times[0], times[3]], "machineID": [1, 1], "comp": ["comp1", "comp1"]}
            ),
            "failures": pd.DataFrame(
                {
                    "datetime": events.tolist() * 2,
                    "machineID": [1] * len(events) + [2] * len(events),
                    "failure": ["comp1"] * (2 * len(events)),
                }
            ),
        }
    )
