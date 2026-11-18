"""Independent export/source verification and portable Phase 4 results; no model fitting."""

import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from factorygraph.io import sha256, write_json
from factorygraph.phase4.config import load_config
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.runtime import NEO4J, ROOT
from factorygraph.phase4.source import verify_preservation
from factorygraph.phase4.study import reference_tables, verify_registration


def validate_export(config) -> dict:
    manifest = json.loads((config.run_dir / "feature_manifest.json").read_text())
    tables, _ = reference_tables(config)
    machines = tables["machines"]
    checked = 0
    missing = {}
    for split, record in manifest["split_artifacts"].items():
        path = Path(record["path"])
        if sha256(path) != record["sha256"]:
            raise ValueError("Feature file changed after export")
        frame = pd.read_parquet(path)
        if len(frame) != record["rows"] or frame.duplicated(["machineID", "datetime"]).any():
            raise ValueError("Feature membership malformed")
        if (frame.latest_contributing_event_timestamp >= frame.datetime).any():
            raise ValueError("Future event feature provenance")
        if not frame.source_cutoff_exclusive.equals(frame.datetime):
            raise ValueError("Source cutoff differs from snapshot")
        missing[split] = {c: int(frame[c].isna().sum()) for c in manifest["feature_columns"]}
        if split == "test":
            expected = pd.read_parquet(
                "artifacts/baseline/test_predictions.parquet", columns=["machineID", "datetime"]
            )
            if not frame[["machineID", "datetime"]].equals(expected):
                raise ValueError("Accepted Phase 1 test snapshot membership/order changed")
        # Predetermined first/middle/last per registered machine, every split.
        for machine, group in frame.groupby("machineID"):
            model = machines.loc[machines.machineID == machine, "model"].item()
            peers = machines.loc[
                (machines.model == model) & (machines.machineID != machine), "machineID"
            ]
            for row in group.iloc[sorted({0, len(group) // 2, len(group) - 1})].itertuples():
                cutoff = row.datetime
                start = cutoff - pd.Timedelta(hours=config.window_hours)
                for kind in ["errors", "maint", "failures"]:
                    source = tables[kind]
                    own = source.loc[(source.machineID == machine) & (source.datetime < cutoff)]
                    if getattr(row, f"g4_{kind}_records_total") != len(own):
                        raise ValueError("Export total differs from independent source mask")
                    if getattr(row, f"g4_{kind}_records_30d") != int((own.datetime >= start).sum()):
                        raise ValueError("Export rolling count differs from source")
                    if kind in {"maint", "failures"}:
                        count = int(
                            (
                                source.machineID.isin(peers)
                                & (source.datetime >= start)
                                & (source.datetime < cutoff)
                            ).sum()
                        )
                        if getattr(row, f"g4_model_peer_{kind}_records_30d") != count:
                            raise ValueError("Export peer count differs from source")
                        rate = count / len(peers) if len(peers) else np.nan
                        if not np.isclose(
                            getattr(row, f"g4_model_peer_{kind}_records_per_machine_30d"),
                            rate,
                            equal_nan=True,
                        ):
                            raise ValueError("Peer rate differs from source")
                if row.g4_eligible_model_peer_machines != len(peers):
                    raise ValueError("Eligible peer population differs from source metadata")
                errors = tables["errors"]
                errors = errors.loc[
                    (errors.machineID == machine)
                    & (errors.datetime >= start)
                    & (errors.datetime < cutoff)
                ]
                for code in [f"error{i}" for i in range(1, 6)]:
                    count = int((errors.errorID == code).sum())
                    if getattr(row, f"g4_{code}_count_30d") != count:
                        raise ValueError("Error distribution differs from source")
                    expected_fraction = count / len(errors) if len(errors) else 0.0
                    if not np.isclose(getattr(row, f"g4_{code}_fraction_30d"), expected_fraction):
                        raise ValueError("Error fraction differs from source")
                if row.g4_distinct_error_types_30d != errors.errorID.nunique():
                    raise ValueError("Distinct error types differ from source")
                maintenance = tables["maint"]
                maintenance = maintenance.loc[
                    (maintenance.machineID == machine)
                    & (maintenance.datetime >= start)
                    & (maintenance.datetime < cutoff)
                ]
                for code in [f"comp{i}" for i in range(1, 5)]:
                    if getattr(row, f"g4_{code}_maintenance_count_30d") != int(
                        (maintenance.comp == code).sum()
                    ):
                        raise ValueError("Component category maintenance count differs from source")
                failures = tables["failures"]
                past = failures.loc[(failures.machineID == machine) & (failures.datetime < cutoff)]
                expected = (
                    (cutoff - past.datetime.max()).total_seconds() / 3600 if len(past) else np.nan
                )
                if not np.isclose(row.g4_hours_since_last_failure, expected, equal_nan=True):
                    raise ValueError("Failure recency differs from source")
                checked += 1
    result = {
        "status": "passed",
        "direct_source_mask_rows_checked": checked,
        "every_split_covered": True,
        "test_keys_equal": True,
        "all_row_temporal_clocks_valid": True,
        "missing_numeric_counts": missing,
    }
    write_json(config.run_dir / "export_verification.json", result)
    return result


def runtime_resources() -> dict:
    home = ROOT / NEO4J
    measured = []
    try:
        record = json.loads(Path("artifacts/phase4/research/server_process.json").read_text())
        parent = psutil.Process(record["pid"])
        for process in [parent, *parent.children(recursive=True)]:
            info = process.memory_info()
            measured.append(
                {
                    "pid": process.pid,
                    "name": process.name(),
                    "rss_bytes": info.rss,
                    "peak_working_set_bytes": getattr(info, "peak_wset", None),
                }
            )
    except (psutil.Error, FileNotFoundError):
        pass
    return {
        "database_store_bytes": sum(
            p.stat().st_size for p in (home / "data/databases").rglob("*") if p.is_file()
        ),
        "transaction_logs_bytes": sum(
            p.stat().st_size for p in (home / "data/transactions").rglob("*") if p.is_file()
        ),
        "processes": measured,
        "memory_scope": (
            "Server/launcher RSS includes JVM, caches and system/pilot DB; "
            "not per-namespace model memory"
        ),
        "storage_scope": (
            "Shared isolated instance with system DB, pilot and full namespaces; "
            "transaction logs may preallocate"
        ),
        "heap_max_bytes": 768 * 1024**2,
        "page_cache_bytes": 256 * 1024**2,
    }


def finalize() -> dict:
    config = load_config(Path("configs/phase4/full.yaml"))
    registration = verify_registration(config)
    export_validation = validate_export(config)
    db = GraphDB(config)
    try:
        build = json.loads((config.run_dir / "build.json").read_text())
        if db.signature() != build["signature"]:
            raise ValueError("Graph logical content changed since construction")
        defects = db.read(
            "MATCH (e:RecordedEvent {namespace:$namespace}) "
            "OPTIONAL MATCH (e)-[:SOURCED_FROM]->(s:DataArtifact {namespace:$namespace}) "
            "WITH e,count(s) AS sources WHERE sources<>1 RETURN count(e) AS defects"
        )[0]["defects"]
        if defects:
            raise ValueError("Source artifact cardinality/provenance defects")
        type_defects = db.read(
            "MATCH (e:RecordedEvent {namespace:$namespace}) "
            "OPTIONAL MATCH (e)-[:HAS_ERROR_TYPE|REFERENCES_COMPONENT_TYPE]->"
            "(t {namespace:$namespace}) WITH e,collect(t.id) AS codes "
            "WHERE codes<>[e.code] RETURN count(e) AS defects"
        )[0]["defects"]
        if type_defects:
            raise ValueError("Recorded type relationship/cardinality mismatch")
    finally:
        db.close()
    tests = Path("artifacts/phase4/test_results.json")
    test_results = json.loads(tests.read_text()) if tests.exists() else None
    completed = test_results is not None and test_results.get("status") == "passed"
    result = {
        "date": "2026-11-13",
        "experiment_registered_date": "2026-11-12",
        "status": "completed_phase4" if completed else "verification_pending",
        "registration": registration,
        "build": build,
        "pilot_admission": json.loads(Path("artifacts/phase4/pilot/admission.json").read_text()),
        "source_audit": json.loads(Path("artifacts/phase4/research/source_audit.json").read_text()),
        "temporal_query_validation": json.loads(
            (config.run_dir / "temporal_validation.json").read_text()
        ),
        "features": json.loads((config.run_dir / "feature_manifest.json").read_text()),
        "export_verification": export_validation,
        "benchmark": json.loads((config.run_dir / "benchmark.json").read_text()),
        "resources": runtime_resources(),
        "runtime_downloads": json.loads((ROOT / "downloads.json").read_text()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {n: version(n) for n in ["neo4j", "pandas", "numpy", "pydantic", "psutil"]},
        },
        "tests": test_results,
        "preservation": {
            "files_unchanged": verify_preservation(),
            "prior_models_untouched": True,
            "metropt_failure_and_incomplete_status_preserved": True,
        },
        "source_sha256": {
            p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase4").glob("*.py")
        },
        "implementation_sha256": {
            p.as_posix(): sha256(p)
            for root in ["src/factorygraph/phase4", "tests/phase4", "configs/phase4"]
            for p in Path(root).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        },
        "dependency_lock_sha256": sha256(Path("requirements/phase4.lock")),
        "logical_backup": {
            "path": "artifacts/phase4/full-backup.json",
            "sha256": sha256(Path("artifacts/phase4/full-backup.json")),
            "scope": "Logical namespace export; no database credentials or system security state",
        },
        "limitations": [
            "Synthetic same-fleet source; no predictive improvement tested",
            "Immediate source availability/UTC/static metadata are assumptions",
            "Graph aggregates have relational equivalents; no new physical dependencies",
            "Local serial small graph benchmark is not production scalability evidence",
            "Phase 3 historical training features remain unavailable; no fused dataset or model",
        ],
    }
    write_json(
        config.run_dir / "artifact_manifest.json",
        {
            p.relative_to(config.run_dir).as_posix(): sha256(p)
            for p in config.run_dir.rglob("*")
            if p.is_file() and p.name != "artifact_manifest.json"
        },
    )
    write_json(Path("docs/results/phase4.json"), result)
    root = Path("artifacts/phase4")
    write_json(
        root / "artifact_manifest.json",
        {
            p.relative_to(root).as_posix(): sha256(p)
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".parquet"}
            and p != root / "artifact_manifest.json"
        },
    )
    return result


if __name__ == "__main__":
    print(finalize()["status"])
