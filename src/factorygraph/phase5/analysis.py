"""Frozen paired outcomes, original operational definitions and machine-cluster uncertainty."""

import json
import time

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score

from factorygraph.evaluation import alert_episodes, evaluate_predictions
from factorygraph.io import verify_artifacts, write_json
from factorygraph.phase5.common import GROUPS, KEYS

CONTRASTS = [
    ("A3", "A0"),
    ("A3", "A4"),
    ("A2", "A1"),
    ("A6", "A3"),
    ("A6", "A2"),
    ("A6", "A5"),
    ("A6", "A0"),
]


def metrics(predictions, failures, threshold):
    result = evaluate_predictions(
        predictions,
        failures,
        threshold=threshold,
        budget_fraction=0.01,
        snapshot_hours=3,
        horizon_hours=24,
        cooldown_hours=24,
    )
    result["f1"] = float(
        f1_score(predictions.label, predictions.probability >= threshold, zero_division=0)
    )
    episodes = alert_episodes(predictions, threshold, 24)
    result["false_alert_episodes"] = int((episodes.label == 0).sum())
    result["alert_rows_per_machine_day"] = (
        result["alerts"] / result["machine_days_snapshot_exposure"]
    )
    return result


def event_outcomes(predictions, failures, threshold):
    episodes = alert_episodes(predictions, threshold, 24)
    rows = []
    for machine, group in predictions.groupby("machineID", sort=True):
        source = failures.loc[failures.machineID == machine]
        alerts = episodes.loc[episodes.machineID == machine, "datetime"]
        for timestamp, records in source.groupby("datetime", sort=True):
            start = timestamp - pd.Timedelta(hours=24)
            if not ((group.datetime >= start) & (group.datetime < timestamp)).any():
                continue
            hit = alerts.loc[(alerts >= start) & (alerts < timestamp)]
            first = hit.min() if len(hit) else pd.NaT
            rows.append(
                {
                    "machineID": machine,
                    "failure_timestamp": timestamp,
                    "event_id": f"phase1-opportunity:{machine}:{timestamp.isoformat()}",
                    "component_codes": "+".join(sorted(records.failure.unique())),
                    "detected": bool(len(hit)),
                    "first_alert": first,
                    "lead_hours": (timestamp - first).total_seconds() / 3600
                    if len(hit)
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def weighted_ap(y, probability, weights):
    order = np.argsort(-probability, kind="stable")
    p = probability[order]
    w = weights[order]
    positive = y[order] * w
    boundaries = np.r_[np.flatnonzero(p[1:] != p[:-1]), len(p) - 1]
    tp = np.cumsum(positive)[boundaries]
    total = np.cumsum(w)[boundaries]
    if not len(tp) or tp[-1] == 0:
        return np.nan
    precision = np.divide(tp, total, out=np.zeros(len(tp)), where=total > 0)
    return float(np.sum(np.diff(np.r_[0, tp]) * precision) / tp[-1])


def bootstrap(predictions, events, draws, seed):
    names = list(predictions)
    reference = predictions[names[0]]
    machines = np.sort(reference.machineID.unique())
    position = {m: i for i, m in enumerate(machines)}
    row_machine = np.array([position[m] for m in reference.machineID])
    y = reference.label.to_numpy()
    rng = np.random.default_rng(seed)
    point = {}
    distributions = {n: {"ap": [], "brier": [], "event_recall": []} for n in names}
    event_counts = {}
    for n in names:
        e = events[n]
        totals = e.groupby("machineID").size().reindex(machines, fill_value=0).to_numpy()
        hits = e.groupby("machineID").detected.sum().reindex(machines, fill_value=0).to_numpy()
        event_counts[n] = (hits, totals)
        p = predictions[n].probability.to_numpy()
        point[n] = {
            "ap": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)),
            "event_recall": float(hits.sum() / totals.sum()),
        }
    for _ in range(draws):
        counts = rng.multinomial(len(machines), np.ones(len(machines)) / len(machines))
        weights = counts[row_machine].astype(float)
        for n in names:
            p = predictions[n].probability.to_numpy()
            hits, totals = event_counts[n]
            distributions[n]["ap"].append(weighted_ap(y, p, weights))
            distributions[n]["brier"].append(float(np.average((y - p) ** 2, weights=weights)))
            distributions[n]["event_recall"].append(float((counts @ hits) / (counts @ totals)))
    contrasts = {}
    for left, right in CONTRASTS:
        contrasts[f"{left}-{right}"] = {}
        for metric in ["ap", "brier", "event_recall"]:
            delta = np.array(distributions[left][metric]) - np.array(distributions[right][metric])
            finite = delta[np.isfinite(delta)]
            contrasts[f"{left}-{right}"][metric] = {
                "difference": point[left][metric] - point[right][metric],
                "percentile_95": [
                    float(np.quantile(finite, 0.025)),
                    float(np.quantile(finite, 0.975)),
                ],
                "paired_machine_draws": len(finite),
            }
    return {
        "draws": draws,
        "seed": seed,
        "cluster": "machine",
        "contrasts": contrasts,
        "interpretation": (
            "Exploratory paired cluster intervals; "
            "not iid rows or multiplicity-adjusted confirmation"
        ),
    }


def analyze(config):
    if not (config.run_dir / "frozen_models.json").exists():
        raise ValueError("Freeze all models before analysis")
    if (config.run_dir / "results.json").exists():
        raise ValueError("Results exist; preserve every outcome")
    start = time.perf_counter()
    failures = pd.read_parquet("artifacts/baseline/evaluation_failures.parquet")
    predictions = {}
    events = {}
    models = {}
    for name in GROUPS:
        directory = config.run_dir / "models" / name
        verify_artifacts(directory)
        policy = json.loads((directory / "policy.json").read_text())
        p = pd.read_parquet(directory / "test_predictions.parquet")
        if predictions:
            first = next(iter(predictions.values()))
            if not p[[*KEYS, "label", "label_end"]].equals(first[[*KEYS, "label", "label_end"]]):
                raise ValueError("Paired evaluation population/labels differ")
        predictions[name] = p
        events[name] = event_outcomes(p, failures, policy["threshold"])
        events[name].to_parquet(directory / "test_events.parquet", index=False)
        metrics_ = metrics(p, failures, policy["threshold"])
        sensitivity = {k: metrics(p, failures, v) for k, v in policy["budgets"].items()}
        monthly = {
            str(month): {
                "rows": len(g),
                "ap": float(average_precision_score(g.label, g.probability)),
                "brier": float(brier_score_loss(g.label, g.probability)),
            }
            for month, g in p.groupby(p.datetime.dt.strftime("%Y-%m"))
        }
        per_machine = {
            str(machine): {
                "rows": len(g),
                "positive_rows": int(g.label.sum()),
                "ap": float(average_precision_score(g.label, g.probability))
                if g.label.sum()
                else None,
                "brier": float(brier_score_loss(g.label, g.probability)),
            }
            for machine, g in p.groupby("machineID")
        }
        models[name] = {
            "test": metrics_,
            "sensitivities": sensitivity,
            "monthly": monthly,
            "per_machine": per_machine,
            "runtime": json.loads((directory / "runtime.json").read_text()),
        }
        for split in ["calibration", "validation"]:
            models[name][split] = metrics(
                pd.read_parquet(directory / f"{split}_predictions.parquet"),
                failures,
                policy["threshold"],
            )
        pd.DataFrame(per_machine).T.to_csv(directory / "per_machine.csv")
    uncertainty = bootstrap(predictions, events, config.bootstrap_draws, config.seed)
    differences = events["A6"].merge(
        events["A0"],
        on=["machineID", "failure_timestamp", "event_id", "component_codes"],
        suffixes=("_A6", "_A0"),
        validate="one_to_one",
    )
    different = differences.loc[differences.detected_A6 != differences.detected_A0].copy()
    different.to_parquet(config.run_dir / "A6_A0_event_differences.parquet", index=False)
    # Descriptive historical feature context at each differing system's first hit only.
    features = pd.read_parquet(config.run_dir / "matched_test.parquet")
    contexts = []
    for row in different.itertuples():
        for model in ["A0", "A6"]:
            hit = getattr(row, f"first_alert_{model}")
            if pd.isna(hit):
                continue
            source = features.loc[
                (features.machineID == row.machineID) & (features.datetime == hit)
            ]
            if len(source) != 1:
                raise ValueError("Detection context not found on matched snapshots")
            fields = [
                "g4_failures_records_total",
                "g4_model_peer_failures_records_30d",
                "p5_c_forecast_age_hours",
                "p5_c_residual_multivariate_mean_latest",
            ]
            vals = {
                c: None if pd.isna(source[c].iloc[0]) else float(source[c].iloc[0]) for c in fields
            }
            contexts.append(
                {
                    "event_id": row.event_id,
                    "model": model,
                    "historical_snapshot": hit.isoformat(),
                    "observed_feature_context": vals,
                    "causal_explanation": False,
                }
            )
    old = pd.read_parquet("artifacts/baseline/test_predictions.parquet")
    a0 = predictions["A0"]
    reproduction = float(np.max(np.abs(old.probability.to_numpy() - a0.probability.to_numpy())))
    controls = float(np.max(np.abs(predictions["A3"].probability - predictions["A4"].probability)))
    primary = uncertainty["contrasts"]["A6-A0"]
    go = (
        primary["ap"]["percentile_95"][0] > 0
        and primary["event_recall"]["percentile_95"][0] > 0
        and models["A6"]["test"]["false_alert_episodes"]
        <= models["A0"]["test"]["false_alert_episodes"]
    )
    result = {
        "status": "completed",
        "primary_model": "A6",
        "models": models,
        "uncertainty": uncertainty,
        "A0_accepted_max_probability_difference": reproduction,
        "A3_A4_max_probability_difference": controls,
        "A6_A0_different_event_count": len(different),
        "event_context": contexts,
        "decision": "GO" if go else "NO-GO for predictive replacement",
        "decision_rule": (
            "Preregistered AP and event-recall lower CI>0; no additional false episodes"
        ),
        "analysis_seconds": time.perf_counter() - start,
        "limitations": [
            "Previously observed synthetic test, not fresh confirmation",
            "One seed/configuration; correlated machines/time and peer features",
            "Graph and relational values are equivalent; storage cannot cause uplift",
            "No real-data fusion or augmented Kumo/stacking experiment",
        ],
    }
    write_json(config.run_dir / "results.json", result)
    return result
