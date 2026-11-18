import json

import numpy as np
import pytest

from factorygraph.phase3.adapter import ChronosAdapter, validate_output
from factorygraph.phase3.config import Phase3Config


@pytest.mark.parametrize("case", ["shape", "nan", "crossed"])
def test_invalid_forecast_outputs_fail(case):
    values = np.tile([0.0, 1.0, 2.0], (2, 4, 24, 1))
    if case == "shape":
        values = values[:1]
    elif case == "nan":
        values[0, 0, 0, 0] = np.nan
    else:
        values[0, 0, 0, :] = [2, 1, 0]
    with pytest.raises(ValueError):
        validate_output(values, (2, 4, 24, 3))


def test_multiple_horizons_and_quantile_shape():
    for horizon in [3, 12, 24]:
        validate_output(np.tile([0.0, 1.0, 2.0], (2, 4, horizon, 1)), (2, 4, horizon, 3))


def test_checkpoint_corruption_fails_before_optional_import(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"revision": "bad"}))
    adapter = ChronosAdapter(Phase3Config(model_dir=tmp_path))
    with pytest.raises(ValueError, match="revision"):
        adapter.load()
    with pytest.raises(RuntimeError, match="Loaded"):
        adapter.predict([])


def test_requested_cuda_never_silently_falls_back(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from factorygraph.phase3.adapter import REVISION, WEIGHTS_SHA256

    manifest = {"revision": REVISION, "files": {"model.safetensors": {"sha256": WEIGHTS_SHA256}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr("factorygraph.phase3.adapter.sha256", lambda path: WEIGHTS_SHA256)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            set_num_threads=lambda n: None,
            manual_seed=lambda n: None,
            cuda=SimpleNamespace(is_available=lambda: False),
        ),
    )
    monkeypatch.setitem(sys.modules, "chronos", SimpleNamespace(Chronos2Pipeline=None))
    adapter = ChronosAdapter(Phase3Config(model_dir=tmp_path, device="cuda"))
    with pytest.raises(RuntimeError, match="no device fallback"):
        adapter.load()
