"""As-of prefix aggregations of genuine graph facts, kept separate from baseline features."""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase4.config import SCHEMA_VERSION, GraphConfig
from factorygraph.phase4.queries import HistoricalQueries


def prefix_count(times: np.ndarray, snapshots: np.ndarray, window_ms: int | None = None):
    end = np.searchsorted(times, snapshots, side="left")
    if window_ms is None:
        return end
    return end - np.searchsorted(times, snapshots - window_ms, side="left")


def compute_features(
    snapshots: pd.DataFrame,
    machines: pd.DataFrame,
    facts: pd.DataFrame,
    config: GraphConfig,
    build_hash: str,
) -> pd.DataFrame:
    keys = ["machineID", "datetime"]
    if snapshots.duplicated(keys).any() or not set(snapshots.machineID).issubset(
        set(machines.machineID)
    ):
        raise ValueError("Snapshot machine/key alignment failed")
    if snapshots.datetime.dt.tz is None:
        raise ValueError("Snapshot timestamps require UTC")
    output = []
    window = config.window_hours * 3600000
    by_machine = {int(m): g for m, g in facts.groupby("machine_id")}
    model_map = machines.set_index("machineID").model.to_dict()
    for machine, group in snapshots.groupby("machineID", sort=False):
        result = group[keys].copy()
        # Pandas timestamp resolution may be us; explicitly use ns conversion before ms.
        cutoffs = group.datetime.to_numpy(dtype="datetime64[ms]").astype("int64")
        own = by_machine.get(int(machine), facts.iloc[:0])
        latest = np.full(len(group), np.iinfo(np.int64).min, dtype=np.int64)
        for kind in ["errors", "maint", "failures"]:
            times = np.sort(own.loc[own.kind == kind, "event_ms"].to_numpy(dtype=np.int64))
            result[f"g4_{kind}_records_total"] = prefix_count(times, cutoffs)
            result[f"g4_{kind}_records_30d"] = prefix_count(times, cutoffs, window)
            pos = np.searchsorted(times, cutoffs, side="left") - 1
            known = pos >= 0
            most_recent = np.full(len(group), np.iinfo(np.int64).min, dtype=np.int64)
            most_recent[known] = times[pos[known]]
            latest = np.maximum(latest, most_recent)
            if kind == "failures":
                elapsed = np.full(len(group), np.nan)
                elapsed[known] = (cutoffs[known] - most_recent[known]) / 3600000
                result["g4_hours_since_last_failure"] = elapsed
        distinct = np.zeros(len(group), dtype=np.int64)
        total_errors = result["g4_errors_records_30d"].to_numpy()
        for code in [f"error{i}" for i in range(1, 6)]:
            times = np.sort(
                own.loc[(own.kind == "errors") & (own.code == code), "event_ms"].to_numpy()
            )
            count = prefix_count(times, cutoffs, window)
            result[f"g4_{code}_count_30d"] = count
            result[f"g4_{code}_fraction_30d"] = np.divide(
                count, total_errors, out=np.zeros(len(group)), where=total_errors > 0
            )
            distinct += count > 0
        result["g4_distinct_error_types_30d"] = distinct
        for code in [f"comp{i}" for i in range(1, 5)]:
            times = np.sort(
                own.loc[(own.kind == "maint") & (own.code == code), "event_ms"].to_numpy()
            )
            result[f"g4_{code}_maintenance_count_30d"] = prefix_count(times, cutoffs, window)
        peers = [
            int(m) for m, v in model_map.items() if v == model_map[int(machine)] and m != machine
        ]
        peer_facts = facts.loc[facts.machine_id.isin(peers)]
        result["g4_eligible_model_peer_machines"] = len(peers)
        for kind in ["failures", "maint"]:
            times = np.sort(peer_facts.loc[peer_facts.kind == kind, "event_ms"].to_numpy())
            count = prefix_count(times, cutoffs, window)
            result[f"g4_model_peer_{kind}_records_30d"] = count
            result[f"g4_model_peer_{kind}_records_per_machine_30d"] = (
                count / len(peers) if peers else np.full(len(group), np.nan)
            )
        peer_times = np.sort(
            peer_facts.loc[peer_facts.kind.isin(["maint", "failures"]), "event_ms"].to_numpy()
        )
        pos = np.searchsorted(peer_times, cutoffs, side="left") - 1
        known = pos >= 0
        if len(peer_times):
            known &= peer_times[np.maximum(pos, 0)] >= cutoffs - window
        latest[known] = np.maximum(latest[known], peer_times[pos[known]])
        result["latest_contributing_event_timestamp"] = pd.to_datetime(
            np.where(latest == np.iinfo(np.int64).min, np.nan, latest.astype(float)),
            unit="ms",
            utc=True,
        )
        result["source_cutoff_exclusive"] = result.datetime
        result["graph_schema_version"] = SCHEMA_VERSION
        result["graph_namespace"] = config.namespace
        result["graph_build_hash"] = build_hash
        result["feature_config_hash"] = config.digest()
        result["provenance_manifest"] = str(config.run_dir / "build.json")
        output.append(result)
    result = pd.concat(output, ignore_index=True)
    # Restore exact source snapshot ordering rather than imposing a new ML row order.
    result = snapshots[keys].merge(result, on=keys, how="left", validate="one_to_one")
    if (result.latest_contributing_event_timestamp >= result.datetime).any():
        raise ValueError("Future event entered graph feature provenance")
    return result


def export_features(db, config: GraphConfig) -> dict:
    started = time.perf_counter()
    from factorygraph.config import load_config as load_baseline
    from factorygraph.features import chronological_split

    snapshots = pd.read_parquet(
        config.processed_dir / "snapshots.parquet", columns=["machineID", "datetime", "label_end"]
    )
    # Reuse accepted calendar/purge membership; no failure labels or future values are read.
    splits = chronological_split(snapshots, load_baseline(Path("configs/baseline.yaml")).split)
    snapshots = pd.concat(
        [frame[["machineID", "datetime"]].assign(split=name) for name, frame in splits.items()],
        ignore_index=True,
    )
    snapshots = snapshots.loc[snapshots.machineID.isin(config.machine_ids)]
    queries = HistoricalQueries(db)
    facts = pd.DataFrame(queries.fleet_facts(snapshots.datetime.max()))
    machines = pd.DataFrame(
        db.read(
            "MATCH (m:Machine {namespace:$namespace}) "
            "-[:HAS_MODEL]->(v:MachineModel) RETURN m.machine_id AS machineID,"
            "v.id AS model ORDER BY machineID"
        )
    )
    build = json.loads((config.run_dir / "build.json").read_text())
    result = compute_features(snapshots, machines, facts, config, build["build_hash"])
    result["split"] = snapshots.split.to_numpy()
    paths = {}
    for split, group in result.groupby("split", sort=False):
        target = config.run_dir / f"features_{split}.parquet"
        if target.exists():
            raise ValueError("Feature export exists; refusing overwrite")
        group.drop(columns="split").to_parquet(target, index=False)
        paths[split] = {"rows": len(group), "path": str(target), "sha256": sha256(target)}
    numeric = [c for c in result if c.startswith("g4_")]
    manifest = {
        "status": "completed",
        "rows": len(result),
        "feature_columns": numeric,
        "split_artifacts": paths,
        "export_seconds": time.perf_counter() - started,
        "schema_version": SCHEMA_VERSION,
        "graph_build_hash": build["build_hash"],
        "config": config.model_dump(mode="json"),
        "keys": ["machineID", "datetime"],
        "visibility": "event_ms < snapshot; rolling windows include lower bound",
        "peer_population": (
            "Other registered machines sharing recorded model; static metadata assumed known"
        ),
        "missing_semantics": (
            "Zero observed counts; missing recency if no historical failure; "
            "missing per-peer rates if no peers; zero fractions if no errors"
        ),
        "novelty": (
            "Same-source historical relational aggregates; model-peer context adds to Phase 1 "
            "features but is not new physical knowledge"
        ),
        "redundancy": (
            "Error distributions/maintenance history overlap conceptually with Phase 1; "
            "30d counts differ from its 3/24/72h error counts and maintenance recency"
        ),
        "provenance": (
            "Each row links namespace/build/config and latest historical event; "
            "build maps graph source IDs to immutable CSV row/hash"
        ),
        "no_fusion_or_label_selection": True,
    }
    write_json(config.run_dir / "feature_manifest.json", manifest)
    return manifest
