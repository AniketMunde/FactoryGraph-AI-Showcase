"""Snapshot and operational metrics, with explicit exposure and alert semantics."""

import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


def budget_threshold(probabilities: np.ndarray, fraction: float) -> float:
    """Conservative threshold: at most floor(N*fraction) validation alerts, ties excluded."""
    p = np.asarray(probabilities, dtype=float)
    if not len(p) or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Expected nonempty finite probabilities in [0,1]")
    if not 0 < fraction < 1:
        raise ValueError("Budget fraction must lie in (0,1)")
    k = math.floor(len(p) * fraction)
    return float(np.nextafter(np.sort(p)[-(k + 1)], np.inf))


def calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    result = []
    assignments = np.minimum((p * bins).astype(int), bins - 1)
    for index in range(bins):
        mask = assignments == index
        result.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": int(mask.sum()),
                "mean_probability": float(p[mask].mean()) if mask.any() else None,
                "observed_frequency": float(y[mask].mean()) if mask.any() else None,
            }
        )
    return result


def alert_episodes(
    predictions: pd.DataFrame, threshold: float, cooldown_hours: int
) -> pd.DataFrame:
    alerts = predictions.loc[predictions.probability >= threshold].sort_values(
        ["machineID", "datetime"]
    )
    selected = []
    for _, group in alerts.groupby("machineID", sort=True):
        last = None
        for index, time in group.datetime.items():
            if last is None or time - last >= pd.Timedelta(hours=cooldown_hours):
                selected.append(index)
                last = time
    return alerts.loc[selected]


def evaluate_predictions(
    predictions: pd.DataFrame,
    failures: pd.DataFrame,
    *,
    threshold: float,
    budget_fraction: float,
    snapshot_hours: int,
    horizon_hours: int,
    cooldown_hours: int,
) -> dict[str, Any]:
    if predictions.empty:
        raise ValueError("Cannot evaluate an empty period")
    y = predictions.label.to_numpy(dtype=int)
    p = predictions.probability.to_numpy(dtype=float)
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Invalid probabilities")
    alerts = p >= threshold
    two_classes = len(np.unique(y)) == 2
    bins = calibration_bins(y, p)
    ece = sum(
        row["count"] / len(y) * abs(row["mean_probability"] - row["observed_frequency"])
        for row in bins
        if row["count"]
    )
    episodes = alert_episodes(predictions, threshold, cooldown_hours)
    # Exposure is evaluated snapshot opportunities, not inferred continuous uptime.
    machine_days = len(predictions) * snapshot_hours / 24
    event_count = 0
    leads = []
    for machine, group in predictions.groupby("machineID", sort=True):
        events = failures.loc[failures.machineID == machine, "datetime"].drop_duplicates()
        # Events must have at least one evaluated opportunity within the target horizon.
        machine_alerts = episodes.loc[episodes.machineID == machine, "datetime"]
        for failure in events:
            start = failure - pd.Timedelta(hours=horizon_hours)
            eligible = (group.datetime >= start) & (group.datetime < failure)
            if not eligible.any():
                continue
            event_count += 1
            hit = machine_alerts[(machine_alerts >= start) & (machine_alerts < failure)]
            if len(hit):
                leads.append((failure - hit.min()).total_seconds() / 3600)
    retrospective = budget_threshold(p, budget_fraction)
    return {
        "rows": len(y),
        "positive_rows": int(y.sum()),
        "prevalence": float(y.mean()),
        "pr_auc_average_precision": float(average_precision_score(y, p)) if y.sum() else None,
        "roc_auc": float(roc_auc_score(y, p)) if two_classes else None,
        "precision": float(precision_score(y, alerts, zero_division=0)),
        "recall": float(recall_score(y, alerts, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece_10_bins": float(ece),
        "calibration_bins": bins,
        "threshold": threshold,
        "alert_fraction": float(alerts.mean()),
        "alerts": int(alerts.sum()),
        "false_alert_rows": int((alerts & (y == 0)).sum()),
        "machine_days_snapshot_exposure": machine_days,
        "false_alert_rows_per_machine_day": float((alerts & (y == 0)).sum() / machine_days),
        "alert_episodes": len(episodes),
        "false_episodes_per_machine_day": float((episodes.label == 0).sum() / machine_days),
        "eligible_failure_events": event_count,
        "detected_failure_events": len(leads),
        "event_recall": len(leads) / event_count if event_count else None,
        "lead_time_hours_median_detected": float(np.median(leads)) if leads else None,
        "lead_time_hours_values_detected": leads,
        "retrospective_recall_at_budget": float(
            recall_score(y, p >= retrospective, zero_division=0)
        ),
        "retrospective_budget_fraction": budget_fraction,
    }
