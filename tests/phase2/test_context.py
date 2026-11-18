import numpy as np
import pandas as pd
import pytest

from factorygraph.phase2.config import Phase2Config
from factorygraph.phase2.context import (
    assert_context_eligible,
    choose_context,
    choose_machines,
    pair_frozen_predictions,
)


def context_rows():
    times = pd.date_range("2015-01-01", periods=100, freq="3h", tz="UTC")
    return pd.DataFrame(
        {
            "machineID": [1] * len(times),
            "datetime": times,
            "label_end": times + pd.Timedelta(hours=24),
            "label": np.arange(len(times)) % 2,
        }
    )


def test_context_is_nested_uniform_and_reproducible():
    rows = context_rows()
    first = choose_context(rows, 16, 42)
    pd.testing.assert_frame_equal(first, choose_context(rows.sample(frac=1), 16, 42))
    pd.testing.assert_frame_equal(first, choose_context(rows, 32, 42).iloc[:16])
    assert set(first.label) == {0, 1}


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_label_must_be_available_strictly_before_query(offset):
    context = context_rows()
    query = pd.DataFrame(
        {"machineID": [2], "datetime": [context.label_end.max() + pd.Timedelta(hours=offset)]}
    )
    if offset > 0:
        assert_context_eligible(context, query)
    else:
        with pytest.raises(ValueError, match="strictly available"):
            assert_context_eligible(context, query)


def test_query_row_labels_and_shortened_horizon_cannot_enter_context():
    context = context_rows()
    query = context.iloc[:1][["machineID", "datetime"]]
    with pytest.raises(ValueError):
        assert_context_eligible(context, query)
    context["label_end"] = context.datetime + pd.Timedelta(hours=1)
    query = pd.DataFrame({"machineID": [2], "datetime": [pd.Timestamp("2016-01-01T00:00Z")]})
    with pytest.raises(ValueError, match="complete prediction horizon"):
        assert_context_eligible(context, query)


def test_membership_pairing_requires_all_query_rows_and_identical_labels():
    query = context_rows().head(5)
    frozen = query.assign(probability=0.3)
    paired = pair_frozen_predictions(query, frozen.sample(frac=1))
    assert len(paired) == len(query)
    with pytest.raises(ValueError, match="missing query rows"):
        pair_frozen_predictions(query, frozen.iloc[:4])
    frozen.loc[0, "label"] = 1 - frozen.loc[0, "label"]
    with pytest.raises(ValueError, match="target labels differ"):
        pair_frozen_predictions(query, frozen)


def test_cohort_selection_uses_ids_only():
    assert choose_machines(list(range(1, 101)), 10, 42) == [1, 13, 41, 45, 53, 54, 64, 84, 86, 88]
    assert choose_machines(list(range(100, 0, -1)), 10, 42) == choose_machines(
        list(range(1, 101)), 10, 42
    )


def test_calibration_and_automatic_device_fallback_are_disabled():
    with pytest.raises(ValueError, match="raw probabilities"):
        Phase2Config(calibration="fit_on_test")
    with pytest.raises(ValueError, match="no silent fallback"):
        Phase2Config(device="auto")
