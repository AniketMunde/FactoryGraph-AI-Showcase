"""One immutable matched population for every registered ablation."""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from factorygraph.io import sha256, write_json
from factorygraph.phase5.common import GROUPS, KEYS, exact_join, splits, verify_registration


def assemble(config):
    verify_registration(config)
    if (config.run_dir / "assembly.json").exists():
        raise ValueError("Assembly exists")
    start = time.perf_counter()
    groups = {
        "A": json.loads(Path("artifacts/baseline/feature_contract.json").read_text())["columns"]
    }
    temporal = json.loads((config.run_dir / "temporal_manifest.json").read_text())
    groups["B"] = temporal["groups"]["b"]["columns"]
    groups["C"] = temporal["groups"]["c"]["columns"]
    graph = json.loads(Path("artifacts/phase4/full/feature_manifest.json").read_text())
    groups["D"] = graph["feature_columns"]
    groups["E"] = groups["D"]
    base = splits(labels=True)
    records = {}
    cache_seconds = 0.0
    for split, frame in base.items():
        result = frame[[*KEYS, "label", "label_end", *groups["A"]]].copy()
        for prefix, family in [("b", "B"), ("c", "C")]:
            data = pd.read_parquet(config.run_dir / f"temporal_{prefix}_{split}.parquet")
            for clock in [
                "latest_source_observation_timestamp",
                "latest_residual_observation_timestamp",
            ]:
                if (data[clock] >= data.datetime).any():
                    raise ValueError("Temporal source after snapshot")
            if (data.forecast_issue_timestamp > data.datetime).any():
                raise ValueError("Future issuance")
            values = exact_join(frame, data, groups[family])
            for c in groups[family]:
                result[c] = values[c].to_numpy()
        tick = time.perf_counter()
        data = pd.read_parquet(graph["split_artifacts"][split]["path"])
        if (
            sha256(Path(graph["split_artifacts"][split]["path"]))
            != graph["split_artifacts"][split]["sha256"]
        ):
            raise ValueError("Accepted graph cache changed")
        if (data.latest_contributing_event_timestamp >= data.datetime).any():
            raise ValueError("Future graph context")
        values = exact_join(frame, data, groups["D"])
        cache_seconds += time.perf_counter() - tick
        relation = pd.read_parquet(config.run_dir / f"relational_{split}.parquet")
        equivalent = exact_join(frame, relation, groups["E"])
        if not np.array_equal(
            values[groups["D"]].to_numpy(), equivalent[groups["E"]].to_numpy(), equal_nan=True
        ):
            raise ValueError("Graph and independent relational values differ")
        for c in groups["D"]:
            result[c] = values[c].to_numpy()
        if np.isinf(
            result[[*groups["A"], *groups["B"], *groups["C"], *groups["D"]]].to_numpy()
        ).any():
            raise ValueError("Infinite model feature")
        target = config.run_dir / f"matched_{split}.parquet"
        result.to_parquet(target, index=False)
        records[split] = {
            "path": str(target),
            "sha256": sha256(target),
            "rows": len(result),
            "positive_rows": int(result.label.sum()),
            "excluded_rows": 0,
            "missing_counts": {c: int(result[c].isna().sum()) for c in result if c not in KEYS},
        }
    output = {
        "status": "completed",
        "groups": groups,
        "ablations": GROUPS,
        "splits": records,
        "graph_relational_exact_equality": True,
        "matched_population": "All accepted rows; no exclusions",
        "seconds": time.perf_counter() - start,
        "graph_cache_load_join_seconds": cache_seconds,
        "missing_policy": "Native NaN; fixed availability and valid counts, no fitted imputation",
    }
    write_json(config.run_dir / "assembly.json", output)
    return output
