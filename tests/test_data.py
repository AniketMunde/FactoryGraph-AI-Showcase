import numpy as np
import pandas as pd
import pytest

from factorygraph.data import SCHEMAS, prepare, quality_report, validate_tables


@pytest.mark.parametrize(
    "case",
    [
        "null",
        "duplicate",
        "id",
        "timestamp",
        "numeric_timestamp",
        "enum",
        "infinite",
        "fractional_id",
        "columns",
        "age",
        "out_of_range",
    ],
)
def test_rejects_invalid_data(tables, case):
    if case == "null":
        tables["telemetry"].loc[0, "volt"] = np.nan
    elif case == "duplicate":
        tables["telemetry"] = pd.concat([tables["telemetry"], tables["telemetry"].iloc[:1]])
    elif case == "id":
        tables["errors"].loc[0, "machineID"] = 999
    elif case == "timestamp":
        tables["errors"]["datetime"] = "invalid"
    elif case == "numeric_timestamp":
        tables["errors"]["datetime"] = [1, 2, 3]
    elif case == "enum":
        tables["maint"].loc[0, "comp"] = "invented"
    elif case == "infinite":
        tables["telemetry"].loc[0, "volt"] = np.inf
    elif case == "fractional_id":
        tables["machines"]["machineID"] = [1.5, 2.0]
    elif case == "columns":
        tables["machines"]["accidental_index"] = 1
    elif case == "age":
        tables["machines"].loc[0, "age"] = -1
    else:
        tables["failures"].loc[0, "datetime"] = pd.Timestamp("2016-01-01", tz="UTC")
    with pytest.raises((ValueError, TypeError)):
        validate_tables(tables)


def test_normalized_parquet_roundtrip_and_provenance(tables, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in SCHEMAS:
        tables[name].to_csv(raw / f"PdM_{name}.csv", index=False)
    normalized = prepare(raw, tmp_path / "processed")
    assert (tmp_path / "processed" / "data_manifest.json").exists()
    assert str(normalized["telemetry"].datetime.dt.tz) == "UTC"
    assert quality_report(normalized)["telemetry"]["non_hourly_intervals"] == 0


def test_multiple_components_same_timestamp_are_valid(tables):
    extra = tables["failures"].iloc[:1].copy()
    extra["failure"] = "comp2"
    tables["failures"] = pd.concat([tables["failures"], extra])
    validate_tables(tables)
