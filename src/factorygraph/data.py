"""Pinned source acquisition, strict table validation, and normalized Parquet storage."""

import json
import logging
import shutil
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json

LOGGER = logging.getLogger(__name__)
SOURCE_REVISION = "e836f4e866028db7fd7d1a66b88f79664a1f4eac"
SOURCE_BASE = (
    "https://raw.githubusercontent.com/microsoft/sqlworkshops/"
    f"{SOURCE_REVISION}/SQLServerAndAzureMachineLearning/ML%20Services%20for%20SQL%20Server"
)
SENSORS = ["volt", "rotate", "pressure", "vibration"]
COMPONENTS = [f"comp{i}" for i in range(1, 5)]
ERRORS = [f"error{i}" for i in range(1, 6)]
SCHEMAS = {
    "machines": ["machineID", "model", "age"],
    "telemetry": ["datetime", "machineID", *SENSORS],
    "errors": ["datetime", "machineID", "errorID"],
    "maint": ["datetime", "machineID", "comp"],
    "failures": ["datetime", "machineID", "failure"],
}


def download(raw_dir: Path) -> None:
    """Download immutable Microsoft-hosted files. Existing downloads are checksum-checked."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "source_manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if old and old.get("revision") != SOURCE_REVISION:
        raise ValueError("Source revision changed; use a separate raw directory")
    records = {}
    for name in SCHEMAS:
        filename = f"PdM_{name}.csv"
        target = raw_dir / filename
        url = f"{SOURCE_BASE}/data/{filename}"
        if target.exists():
            expected = old.get("files", {}).get(filename, {}).get("sha256")
            if not expected or sha256(target) != expected:
                raise ValueError(f"Unverified existing file {target}; use prepare for manual files")
        else:
            partial = target.with_suffix(".csv.part")
            LOGGER.info("downloading %s", filename)
            request = urllib.request.Request(url, headers={"User-Agent": "FactoryGraph/0.1"})
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    with partial.open("wb") as stream:
                        shutil.copyfileobj(response, stream)
                # A Git LFS pointer or HTML error must never masquerade as CSV.
                with partial.open("r", encoding="utf-8-sig") as stream:
                    header = stream.readline().strip().replace('"', "").split(",")
                if header != SCHEMAS[name]:
                    raise ValueError(f"Unexpected download header for {filename}: {header}")
                partial.replace(target)
            except Exception:
                partial.unlink(missing_ok=True)
                raise
        records[filename] = {"url": url, "sha256": sha256(target), "bytes": target.stat().st_size}
        # Persist each successful file so interrupted downloads can safely resume.
        write_json(
            manifest_path,
            {
                "revision": SOURCE_REVISION,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "files": {**old.get("files", {}), **records},
                "license_url": f"https://github.com/microsoft/sqlworkshops/blob/{SOURCE_REVISION}/LICENSE",
            },
        )
    license_path = raw_dir / "UPSTREAM_LICENSE.txt"
    if not license_path.exists():
        with urllib.request.urlopen(
            f"https://raw.githubusercontent.com/microsoft/sqlworkshops/{SOURCE_REVISION}/LICENSE",
            timeout=30,
        ) as response:
            license_path.write_bytes(response.read())


def validate_tables(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Fail fast on schema, null, ID, enum, timestamp, finite-value or key violations."""
    if set(tables) != set(SCHEMAS):
        raise ValueError("Exactly the five Azure source tables are required")
    clean = {}
    for name, columns in SCHEMAS.items():
        df = tables[name].copy()
        if set(df.columns) != set(columns):
            raise ValueError(f"{name}: expected columns {columns}")
        if df.isna().any().any():
            raise ValueError(f"{name}: missing source values")
        ids = pd.to_numeric(df["machineID"], errors="raise")
        if not np.isfinite(ids).all() or (ids <= 0).any() or (ids % 1 != 0).any():
            raise ValueError(f"{name}: machineID must be positive integers")
        df["machineID"] = ids.astype("int64")
        if "datetime" in df:
            if pd.api.types.is_numeric_dtype(df["datetime"]):
                raise ValueError(f"{name}: numeric timestamps are not supported")
            df["datetime"] = pd.to_datetime(
                df["datetime"], errors="raise", utc=True, format="mixed"
            )
            if df["datetime"].isna().any():
                raise ValueError(f"{name}: invalid timestamps")
        for field in SENSORS if name == "telemetry" else ["age"] if name == "machines" else []:
            df[field] = pd.to_numeric(df[field], errors="raise").astype("float64")
            if not np.isfinite(df[field]).all():
                raise ValueError(f"{name}: nonfinite {field}")
        if name == "machines" and (df["age"] < 0).any():
            raise ValueError("machines: age cannot be negative")
        enums = {
            "model": [f"model{i}" for i in range(1, 5)],
            "errorID": ERRORS,
            "comp": COMPONENTS,
            "failure": COMPONENTS,
        }
        for field, allowed in enums.items():
            if field in df and not df[field].isin(allowed).all():
                raise ValueError(f"{name}: unknown {field}")
        key = ["machineID"] if name == "machines" else columns[:2]
        if name in {"errors", "maint", "failures"}:
            key = columns
        if df.duplicated(key).any():
            raise ValueError(f"{name}: duplicate keys {key}")
        if name in {"telemetry", "machines"} and df.empty:
            raise ValueError(f"{name}: cannot be empty")
        clean[name] = df.sort_values(key).reset_index(drop=True)
    known = set(clean["machines"]["machineID"])
    for name, df in clean.items():
        if not set(df["machineID"]).issubset(known):
            raise ValueError(f"{name}: unknown machineID")
    if set(clean["telemetry"]["machineID"]) != known:
        raise ValueError("Every machine requires telemetry coverage")
    bounds = clean["telemetry"].groupby("machineID")["datetime"].agg(["min", "max"])
    for name in ["errors", "failures"]:
        events = clean[name].join(bounds, on="machineID")
        if ((events.datetime < events["min"]) | (events.datetime > events["max"])).any():
            raise ValueError(f"{name}: events outside observed telemetry range")
    return clean


def quality_report(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name, df in tables.items():
        info: dict[str, Any] = {
            "rows": len(df),
            "machines": int(df.machineID.nunique()),
            "missing_values": int(df.isna().sum().sum()),
        }
        if "datetime" in df:
            info.update(
                start=df.datetime.min().isoformat() if len(df) else None,
                end=df.datetime.max().isoformat() if len(df) else None,
            )
        report[name] = info
    delta = tables["telemetry"].groupby("machineID").datetime.diff().dropna()
    report["telemetry"]["non_hourly_intervals"] = int((delta != pd.Timedelta(hours=1)).sum())
    return report


def prepare(raw_dir: Path, processed_dir: Path) -> dict[str, pd.DataFrame]:
    source = raw_dir / "source_manifest.json"
    if source.exists():
        source_files = json.loads(source.read_text())["files"]
        for name in SCHEMAS:
            filename = f"PdM_{name}.csv"
            if source_files.get(filename, {}).get("sha256") != sha256(raw_dir / filename):
                raise ValueError(f"Raw file changed since acquisition: {filename}")
    tables = validate_tables({name: pd.read_csv(raw_dir / f"PdM_{name}.csv") for name in SCHEMAS})
    processed_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(processed_dir / f"{name}.parquet", index=False)
    provenance = {
        "processed_at": datetime.now(UTC).isoformat(),
        "timezone_policy": "UTC assumed; original timestamps have no zone",
        "raw_sha256": {name: sha256(raw_dir / f"PdM_{name}.csv") for name in SCHEMAS},
        "quality": quality_report(tables),
    }
    provenance["source"] = (
        json.loads(source.read_text())
        if source.exists()
        else {
            "mode": "manual",
            "origin": "unverified; supply external provenance before reporting results",
        }
    )
    write_json(processed_dir / "data_manifest.json", provenance)
    return tables


def load_tables(processed_dir: Path) -> dict[str, pd.DataFrame]:
    return validate_tables(
        {name: pd.read_parquet(processed_dir / f"{name}.parquet") for name in SCHEMAS}
    )
