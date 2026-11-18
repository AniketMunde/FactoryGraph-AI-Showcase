"""Mocks here test software contracts only; benchmark results use real pretrained inference."""

from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from factorygraph.phase2.adapter import (
    KumoAdapter,
    ModelInferenceError,
    ModelLoadError,
    validate_features,
    validate_probabilities,
)
from factorygraph.phase2.config import Phase2Config


def frame():
    return pd.DataFrame(
        {
            "machineID": [1, 2],
            "datetime": pd.to_datetime(["2015-10-01T00:00Z", "2015-10-01T00:00Z"]),
            "model_code": [1, 4],
            "numeric": [2.0, np.nan],
        }
    )


def test_feature_schema_retains_categorical_vocabulary_and_missing_history():
    values = validate_features(frame(), ["model_code", "numeric"])
    assert isinstance(values.model_code.dtype, pd.CategoricalDtype)
    assert values.model_code.cat.categories.tolist() == [1, 2, 3, 4]
    assert values.numeric.isna().sum() == 1


@pytest.mark.parametrize("case", ["label", "missing", "infinite", "category", "text"])
def test_feature_schema_rejects_incompatible_or_leaking_inputs(case):
    query = frame()
    if case == "label":
        query["label"] = 1
    elif case == "missing":
        query = query.drop(columns="numeric")
    elif case == "infinite":
        query.loc[0, "numeric"] = np.inf
    elif case == "category":
        query.loc[0, "model_code"] = 5
    else:
        query["numeric"] = "bad"
    with pytest.raises(ValueError):
        validate_features(query, ["model_code", "numeric"])


@pytest.mark.parametrize(
    "values",
    [
        [[0.1, 0.2]],
        [[-0.1, 1.1]],
        [[np.nan, 0.5]],
        [[0.5]],
        [[0.3, 0.7], [0.4, 0.6]],
    ],
)
def test_invalid_class_probabilities_raise(values):
    with pytest.raises(ModelInferenceError):
        validate_probabilities(np.array(values), 1)


def test_valid_binary_probabilities_are_not_reinterpreted():
    values = np.array([[0.2, 0.8], [0.6, 0.4]])
    np.testing.assert_array_equal(validate_probabilities(values, 2), values)


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class FakeTable:
    def __getitem__(self, item):
        values = np.array([0.8, 0.4]) if item[1] == "1" else np.array([0.2, 0.6])
        return SimpleNamespace(numerical=FakeTensor(values))


def test_adapter_class_order_shape_and_failure_contract():
    adapter = KumoAdapter(Phase2Config(device="cpu"), ["model_code", "numeric"])
    with pytest.raises(ModelInferenceError, match="eligible context"):
        adapter.predict(frame())
    with pytest.raises(ModelLoadError):
        adapter.set_context(frame())
    adapter.context = pd.DataFrame(
        {
            "machineID": [3],
            "datetime": [pd.Timestamp("2015-01-01T00:00Z")],
            "label_end": [pd.Timestamp("2015-01-02T00:00Z")],
        }
    )
    adapter.torch = SimpleNamespace(inference_mode=nullcontext)
    adapter.sdm = SimpleNamespace(
        TableTensor=SimpleNamespace(from_pandas=lambda *args, **kwargs: None),
        infer_stypes=lambda values: {},
    )
    adapter.model = SimpleNamespace(predict=lambda values: FakeTable())
    probabilities, timing = adapter.predict(frame())
    np.testing.assert_allclose(probabilities, [[0.2, 0.8], [0.6, 0.4]])
    assert timing["total_seconds"] >= timing["sdk_predict_seconds"]

    def fail(_):
        raise RuntimeError("injected failure")

    adapter.model = SimpleNamespace(predict=fail)
    with pytest.raises(ModelInferenceError, match="injected failure"):
        adapter.predict(frame())


def test_missing_checkpoint_is_a_load_failure(tmp_path):
    # No optional runtime import is required to test a real load failure in Phase 1's env.
    adapter = KumoAdapter(Phase2Config(model_dir=tmp_path), ["model_code", "numeric"])
    with pytest.raises(ModelLoadError):
        adapter.load()
