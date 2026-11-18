"""Audited source rows and identities; categorical components are never physical instances."""

import hashlib
import json
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from factorygraph.data import SCHEMAS, SOURCE_REVISION, validate_tables
from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase4.config import GraphConfig, milliseconds

EVENTS = {
    "errors": ("ErrorEvent", "errorID", "ErrorType", "RECORDED_ERROR", "HAS_ERROR_TYPE"),
    "maint": (
        "MaintenanceEvent",
        "comp",
        "ComponentType",
        "HAS_MAINTENANCE_EVENT",
        "REFERENCES_COMPONENT_TYPE",
    ),
    "failures": (
        "FailureEvent",
        "failure",
        "ComponentType",
        "HAS_FAILURE_EVENT",
        "REFERENCES_COMPONENT_TYPE",
    ),
}


def identity(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


class EventFact(BaseModel):
    id: str
    machine_id: int = Field(gt=0)
    kind: Literal["errors", "maint", "failures"]
    code: str
    event_ms: int
    event_timestamp: str
    source_table: str
    source_row: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_dataset: str = f"microsoft-azure-synthetic:{SOURCE_REVISION}"
    source_record_id: str
    source_payload_sha256: str
    visibility_policy: str = "event_time_assumed_available;strict_before_cutoff"


def read_sources(config: GraphConfig) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    manifest = json.loads((config.raw_dir / "source_manifest.json").read_text())
    if manifest["revision"] != SOURCE_REVISION:
        raise ValueError("Source revision differs from accepted dataset")
    raw, hashes = {}, {}
    for name in SCHEMAS:
        path = config.raw_dir / f"PdM_{name}.csv"
        digest = sha256(path)
        if digest != manifest["files"][path.name]["sha256"]:
            raise ValueError("Source file failed integrity validation")
        raw[name] = pd.read_csv(path)
        hashes[name] = digest
    validate_tables(raw)  # Keep original CSV row positions rather than sorted validator output.
    if not set(config.machine_ids).issubset(set(raw["machines"].machineID)):
        raise ValueError("Unknown machine in registered membership")
    for frame in raw.values():
        if "datetime" in frame:
            frame["datetime"] = pd.to_datetime(frame.datetime, utc=True, format="mixed")
    return raw, hashes


def event_facts(tables: dict[str, pd.DataFrame], hashes: dict[str, str], machines: list[int]):
    records = []
    for table, (_, field, *_rest) in EVENTS.items():
        for offset, row in enumerate(tables[table].itertuples(index=False), start=1):
            if row.machineID not in machines:
                continue
            code = getattr(row, field)
            if code not in (
                [f"error{i}" for i in range(1, 6)]
                if table == "errors"
                else [f"comp{i}" for i in range(1, 5)]
            ):
                raise ValueError("Unknown recorded category")
            record_id = f"PdM_{table}.csv:data-row:{offset}"
            fact = EventFact(
                id=identity(SOURCE_REVISION, hashes[table], record_id),
                machine_id=row.machineID,
                kind=table,
                code=code,
                event_ms=milliseconds(row.datetime),
                event_timestamp=row.datetime.isoformat(),
                source_table=f"PdM_{table}.csv",
                source_row=offset,
                source_sha256=hashes[table],
                source_record_id=record_id,
                source_payload_sha256=identity(row.machineID, row.datetime.isoformat(), code),
            )
            records.append(fact.model_dump())
    return sorted(records, key=lambda r: (r["event_ms"], r["kind"], r["id"]))


def verify_preservation(path: Path = Path("artifacts/phase4/protected.json")) -> int:
    values = json.loads(path.read_text())
    for name, digest in values.items():
        if sha256(Path(name)) != digest:
            raise ValueError(f"Historical file changed: {name}")
    return len(values)


def audit(config: GraphConfig) -> dict:
    """Reproducible Gate A/B; only capture a new preservation manifest after prior checks."""
    for root in [
        "artifacts/baseline",
        "artifacts/phase2/kumo-full",
        "artifacts/phase3/azure",
        "artifacts/phase3/metropt",
    ]:
        verify_artifacts(Path(root))
    previous = json.loads(Path("docs/results/phase3.json").read_text())
    for path, digest in previous["source_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("Accepted Phase 3 source changed")
    from factorygraph.phase3.integrity import verify

    verify(Path("artifacts/phase3/azure/protected.json"))
    target = Path("artifacts/phase4/protected.json")
    if target.exists():
        count = verify_preservation(target)
    else:
        paths = set()
        for root in [
            "artifacts/baseline",
            "artifacts/phase2",
            "artifacts/phase3",
            "data/raw/azure",
            "data/processed/azure",
            "data/phase3",
            "data/models/phase3",
            "src/factorygraph",
            "configs",
            "requirements",
            "tests",
        ]:
            paths.update(
                p
                for p in Path(root).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and "phase4" not in p.parts
            )
        paths.update(
            p
            for p in Path("docs").rglob("*")
            if p.is_file()
            and p.name not in {"ARCHITECTURE.md", "ROADMAP.md", "DECISIONS.md"}
            and "phase4" not in p.name.lower()
        )
        paths.add(Path("requirements.lock"))
        write_json(target, {p.as_posix(): sha256(p) for p in sorted(paths)})
        count = len(paths)
    tables, hashes = read_sources(config)
    audited = validate_tables(tables)
    report = {}
    for name, frame in audited.items():
        report[name] = {
            "rows": len(frame),
            "dtypes": {c: str(v) for c, v in frame.dtypes.items()},
            "same_machine_timestamp_rows": int(
                frame.duplicated(["machineID", "datetime"], keep=False).sum()
            )
            if "datetime" in frame
            else 0,
            "categories": {
                c: sorted(frame[c].unique().tolist())
                for c in ["model", "errorID", "comp", "failure"]
                if c in frame
            },
            "sha256": hashes[name],
        }
    overlap = tables["failures"].merge(
        tables["maint"],
        left_on=["machineID", "datetime", "failure"],
        right_on=["machineID", "datetime", "comp"],
        validate="one_to_one",
    )
    report["overlap"] = {
        "exact_failure_maintenance_category_matches": len(overlap),
        "failure_rows": len(tables["failures"]),
        "interpretation": (
            "Two recorded source facts; no assertion of one physical repair event or causation"
        ),
    }
    path = Path("artifacts/phase4/research/source_audit.json")
    if path.exists():
        if json.loads(path.read_text()) != report:
            raise ValueError("Existing source audit differs from actual sources")
    else:
        write_json(path, report)
    return {
        "status": "passed",
        "protected_files": count,
        "source_rows": {name: len(frame) for name, frame in tables.items()},
    }
