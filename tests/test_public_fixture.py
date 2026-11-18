"""Illustrative fixtures must not acquire accepted research identity."""

import json
from pathlib import Path

import pytest

from factorygraph.phase6.schema import CaseReport


def test_fixture_is_unscored_and_has_no_source_records():
    value = json.loads(Path("tests/fixtures/illustrative_case.json").read_text())
    report = CaseReport.model_validate(value)
    assert report.provenance["classification"] == "illustrative_generated_fixture"
    assert report.prediction.probability is None
    assert report.prediction.model_sha256 is None
    assert report.prediction.status == "unavailable"
    assert not report.historical_evidence["facts"]


def test_full_mode_does_not_select_fixture(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from factorygraph.phase7.config import Settings
    from factorygraph.phase7.runtime import Runtime

    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        Runtime(Settings())


def test_genuine_gallery_needs_authorized_cases(tmp_path):
    pytest.importorskip("fastapi")
    from factorygraph.phase7.config import Settings
    from factorygraph.phase7.runtime import Runtime

    with pytest.raises(FileNotFoundError):
        Runtime(Settings(mode="gallery", gallery_directory=tmp_path))
