"""Independent relational as-of control; does not call Phase 4 feature code."""

import time

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase5.common import KEYS, splits


def past_counts(events, timestamps):
    """Cumulative SQL/as-of equivalent with strict historical matching, preserving row order."""
    if not len(events):
        return np.zeros(len(timestamps), dtype=np.int64)
    right = events.groupby(events).size().sort_index().cumsum().rename("count").reset_index()
    right.columns = ["event_time", "count"]
    right["event_time"] = pd.DatetimeIndex(right.event_time).as_unit("ns")
    left = pd.DataFrame(
        {"cutoff": pd.DatetimeIndex(timestamps).as_unit("ns"), "position": range(len(timestamps))}
    )
    joined = pd.merge_asof(
        left.sort_values("cutoff"),
        right,
        left_on="cutoff",
        right_on="event_time",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("position")
    return joined["count"].fillna(0).to_numpy(dtype=np.int64)


def past_time(events, timestamps):
    if not len(events):
        return pd.Series(pd.NaT, index=timestamps, dtype="datetime64[ns, UTC]")
    right = pd.DataFrame(
        {"event_time": pd.DatetimeIndex(events).as_unit("ns").sort_values().unique()}
    )
    left = pd.DataFrame(
        {"cutoff": pd.DatetimeIndex(timestamps).as_unit("ns"), "position": range(len(timestamps))}
    )
    joined = pd.merge_asof(
        left.sort_values("cutoff"),
        right,
        left_on="cutoff",
        right_on="event_time",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("position")
    return pd.Series(joined.event_time.to_numpy(), index=timestamps)


def compute(snapshots, tables):
    frames = []
    models = tables["machines"].set_index("machineID").model
    for machine, group in snapshots.groupby("machineID", sort=False):
        out = group[KEYS].copy().set_index("datetime")
        times = out.index
        start = times - pd.Timedelta(days=30)
        own = {
            k: tables[k].loc[tables[k].machineID == machine]
            for k in ["errors", "maint", "failures"]
        }
        for kind, table in own.items():
            out[f"g4_{kind}_records_total"] = past_counts(table.datetime, times)
            out[f"g4_{kind}_records_30d"] = out[
                f"g4_{kind}_records_total"
            ].to_numpy() - past_counts(table.datetime, start)
        recent = past_time(own["failures"].datetime, times)
        out["g4_hours_since_last_failure"] = (times.to_series() - recent).dt.total_seconds() / 3600
        distinct = np.zeros(len(times), dtype=np.int64)
        for code in [f"error{i}" for i in range(1, 6)]:
            events = own["errors"].loc[own["errors"].errorID == code, "datetime"]
            counts = past_counts(events, times) - past_counts(events, start)
            out[f"g4_{code}_count_30d"] = counts
            total = out.g4_errors_records_30d.to_numpy()
            out[f"g4_{code}_fraction_30d"] = np.divide(
                counts, total, out=np.zeros(len(times)), where=total > 0
            )
            distinct += counts > 0
        out["g4_distinct_error_types_30d"] = distinct
        for code in [f"comp{i}" for i in range(1, 5)]:
            events = own["maint"].loc[own["maint"].comp == code, "datetime"]
            out[f"g4_{code}_maintenance_count_30d"] = past_counts(events, times) - past_counts(
                events, start
            )
        peers = models.loc[(models == models[machine]) & (models.index != machine)].index
        out["g4_eligible_model_peer_machines"] = len(peers)
        for kind in ["failures", "maint"]:
            events = tables[kind].loc[tables[kind].machineID.isin(peers), "datetime"]
            counts = past_counts(events, times) - past_counts(events, start)
            out[f"g4_model_peer_{kind}_records_30d"] = counts
            out[f"g4_model_peer_{kind}_records_per_machine_30d"] = (
                counts / len(peers) if len(peers) else np.nan
            )
        own_latest = pd.concat([past_time(t.datetime, times) for t in own.values()], axis=1).max(
            axis=1
        )
        peer_latest = []
        for kind in ["failures", "maint"]:
            events = tables[kind].loc[tables[kind].machineID.isin(peers), "datetime"]
            previous = past_time(events, times)
            peer_latest.append(previous.where(previous >= start))
        out["source_max"] = pd.concat([own_latest, *peer_latest], axis=1).max(axis=1)
        frames.append(out.reset_index())
    result = pd.concat(frames, ignore_index=True)
    if (result.source_max >= result.datetime).any():
        raise ValueError("Future relational feature")
    return snapshots[KEYS].merge(result, on=KEYS, how="left", validate="one_to_one")


def export(config):
    start = time.perf_counter()
    tables = {
        name: pd.read_parquet(f"data/processed/azure/{name}.parquet")
        for name in ["machines", "errors", "maint", "failures"]
    }
    frames = splits()
    keys = pd.concat([f[KEYS] for f in frames.values()], ignore_index=True)
    result = compute(keys, tables)
    records = {}
    for split, frame in frames.items():
        selected = frame[KEYS].merge(result, on=KEYS, validate="one_to_one")
        target = config.run_dir / f"relational_{split}.parquet"
        if target.exists():
            raise ValueError("Relational output exists")
        selected.to_parquet(target, index=False)
        records[split] = {"path": str(target), "sha256": sha256(target), "rows": len(selected)}
    output = {
        "status": "completed",
        "seconds": time.perf_counter() - start,
        "splits": records,
        "algorithm": "Independent source-table cumulative merge_asof with exact matches excluded",
    }
    write_json(config.run_dir / "relational_manifest.json", output)
    return output
