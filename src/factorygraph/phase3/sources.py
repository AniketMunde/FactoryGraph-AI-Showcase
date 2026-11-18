"""Public source acquisition and causal MetroPT preparation, without changing prior data."""

import shutil
import urllib.request
import zipfile
from importlib.metadata import distribution
from pathlib import Path

import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase3.adapter import REVISION, WEIGHTS_SHA256

FILES = {
    "model.safetensors": WEIGHTS_SHA256,
    "config.json": "ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031",
    "README.md": "c7b29bc88f5bc3ebc6e7213b6353be80090d671fefa4aa74ed20498838c16558",
}
METRO_SHA256 = "aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a"
ANALOG = ["TP2", "TP3", "H1", "DV_pressure", "Reservoirs", "Oil_temperature", "Motor_current"]


def acquire_file(url: str, path: Path, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha256(path) != digest:
            raise ValueError(f"Existing source checksum mismatch: {path}")
        return
    partial = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=180) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if sha256(partial) != digest:
            raise ValueError(f"Downloaded checksum mismatch: {path}")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def acquire(model_dir: Path) -> None:
    for filename, digest in FILES.items():
        acquire_file(
            f"https://huggingface.co/amazon/chronos-2/resolve/{REVISION}/{filename}",
            model_dir / filename,
            digest,
        )
    notice = model_dir / "LICENSE_UPSTREAM.txt"
    if not notice.exists():
        package = distribution("chronos-forecasting")
        license_file = next(p for p in package.files if p.name == "LICENSE")
        notice.write_bytes(package.locate_file(license_file).read_bytes())
    if not (model_dir / "manifest.json").exists():
        write_json(
            model_dir / "manifest.json",
            {
                "repo": "amazon/chronos-2",
                "revision": REVISION,
                "license": "Apache-2.0 (model-card declaration)",
                "files": {
                    p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                    for p in model_dir.iterdir()
                    if p.is_file()
                },
            },
        )
    root = Path("data/phase3/metropt")
    acquire_file(
        "https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip",
        root / "source.zip",
        METRO_SHA256,
    )
    if not (root / "download.json").exists():
        write_json(
            root / "download.json",
            {
                "url": "https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip",
                "sha256": METRO_SHA256,
                "license": "CC-BY-4.0",
                "doi": "10.24432/C5VW3R",
            },
        )


def prepare_metro() -> dict:
    root = Path("data/phase3/metropt")
    if sha256(root / "source.zip") != METRO_SHA256:
        raise ValueError("MetroPT archive integrity failed")
    with zipfile.ZipFile(root / "source.zip") as archive:
        with archive.open("MetroPT3(AirCompressor).csv") as stream:
            frame = pd.read_csv(stream)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    if frame.timestamp.duplicated().any() or not frame.timestamp.is_monotonic_increasing:
        raise ValueError("MetroPT timestamp ordering/uniqueness failed")
    delta = frame.timestamp.diff().dt.total_seconds().dropna()
    raw = frame.set_index("timestamp")
    counts = raw.resample("h", closed="left", label="right").size()
    hourly = raw[ANALOG].resample("h", closed="left", label="right").mean()
    hourly.loc[counts < 270, :] = float("nan")
    hourly = hourly.reset_index().rename(columns={"timestamp": "datetime"})
    hourly["machineID"] = 1
    candidate = root / "hourly.candidate.csv"
    hourly.to_csv(candidate, index=False)
    target = root / "hourly.csv"
    if target.exists() and sha256(target) != sha256(candidate):
        candidate.unlink()
        raise ValueError("Existing prepared MetroPT differs; use a new experiment directory")
    if target.exists():
        candidate.unlink()
    else:
        candidate.replace(target)
    counts.rename("observations").to_csv(root / "hourly_coverage.csv")
    record = {
        "raw_rows": len(frame),
        "median_interval_seconds": float(delta.median()),
        "gaps_over_60s": int((delta > 60).sum()),
        "hourly_rows": len(hourly),
        "invalid_hourly_bins": int(hourly[ANALOG].isna().any(axis=1).sum()),
        "channels": ANALOG,
        "hourly_sha256": sha256(target),
        "archive_sha256": METRO_SHA256,
        "resampling": "[T-1h,T) mean labeled T; >=270 observations; no filling",
        "timezone": "UTC assumed, not verified source geography",
    }
    write_json(root / "preparation_manifest.json", record)
    return record
