"""Descriptive training-only attribution and redundancy; never causal explanation or selection."""

import json

import numpy as np
import pandas as pd

from factorygraph.io import write_json
from factorygraph.phase5.common import GROUPS


def inspect(config):
    assembly = json.loads((config.run_dir / "assembly.json").read_text())
    summaries = {}
    for name, families in GROUPS.items():
        importance = pd.read_csv(config.run_dir / "models" / name / "feature_importance.csv")
        mapping = {c: g for g in families for c in assembly["groups"][g]}
        importance["family"] = importance.feature.map(mapping)
        total = importance.gain.sum()
        family = {
            str(g): {
                "gain": float(x.gain.sum()),
                "fraction": float(x.gain.sum() / total),
                "columns": len(x),
                "used_columns": int((x.gain > 0).sum()),
            }
            for g, x in importance.groupby("family")
        }
        summaries[name] = {
            "families": family,
            "top_features": importance.sort_values("gain", ascending=False)
            .head(15)
            .to_dict("records"),
        }
    train = pd.read_parquet(config.run_dir / "matched_train.parquet")
    columns = [
        c for group in ["A", "B", "C", "D"] for c in assembly["groups"][group] if c != "model_code"
    ]
    sample = train[columns].sample(n=min(10000, len(train)), random_state=config.seed)
    correlation = sample.corr()
    values = correlation.to_numpy()
    upper = np.triu(np.ones(values.shape, dtype=bool), 1)
    indices = np.argwhere(upper & (np.abs(values) >= 0.98))
    pairs = sorted(
        [
            {"left": columns[i], "right": columns[j], "pearson": float(values[i, j])}
            for i, j in indices
        ],
        key=lambda r: -abs(r["pearson"]),
    )[:50]
    output = {
        "status": "completed",
        "scope": "Training-only gain and fixed training sample Pearson correlations",
        "models": summaries,
        "highly_correlated_pairs": pairs,
        "zero_variance_training_columns": [
            c for c in columns if sample[c].nunique(dropna=True) <= 1
        ],
        "limitations": [
            "Gain favors available split opportunities and correlated substitutes",
            "Different family sizes are not controlled by raw importance",
            "Warm-up missingness/calendar/model-group patterns can be synthetic shortcuts",
            "Attribution is association, not physical causation; no feature selection performed",
        ],
    }
    write_json(config.run_dir / "contribution.json", output)
    return output
