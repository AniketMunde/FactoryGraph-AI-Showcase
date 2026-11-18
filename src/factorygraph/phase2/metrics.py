"""Paired Phase 1 metrics with explicit complete-window event eligibility."""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score

from factorygraph.config import ExperimentConfig
from factorygraph.evaluation import evaluate_predictions


def complete_window_failures(
    query: pd.DataFrame, failures: pd.DataFrame, horizon_hours: int, snapshot_hours: int
) -> tuple[pd.DataFrame, dict[str, int]]:
    selected = []
    considered = 0
    for machine, group in query.groupby("machineID"):
        times = pd.DatetimeIndex(group.datetime)
        events = failures.loc[failures.machineID == machine].drop_duplicates(
            ["machineID", "datetime"]
        )
        for index, event in events.iterrows():
            start = event.datetime - pd.Timedelta(hours=horizon_hours)
            if not ((times >= start) & (times < event.datetime)).any():
                continue
            considered += 1
            expected = pd.date_range(
                start.ceil(f"{snapshot_hours}h"),
                event.datetime,
                freq=f"{snapshot_hours}h",
                inclusive="left",
            )
            if len(expected) and expected.isin(times).all():
                selected.append(index)
    return failures.loc[selected].copy(), {
        "events_with_any_opportunity": considered,
        "events_with_complete_window": len(selected),
        "events_excluded_incomplete_window": considered - len(selected),
    }


def score(
    predictions: pd.DataFrame,
    failures: pd.DataFrame,
    threshold: float,
    baseline_config: ExperimentConfig,
) -> dict[str, Any]:
    eligible, coverage = complete_window_failures(
        predictions,
        failures,
        baseline_config.features.horizon_hours,
        baseline_config.features.snapshot_hours,
    )
    result = evaluate_predictions(
        predictions,
        eligible,
        threshold=threshold,
        budget_fraction=baseline_config.alert_budget_fraction,
        snapshot_hours=baseline_config.features.snapshot_hours,
        horizon_hours=baseline_config.features.horizon_hours,
        cooldown_hours=baseline_config.cooldown_hours,
    )
    alert = predictions.probability.to_numpy() >= threshold
    result["f1"] = float(f1_score(predictions.label, alert, zero_division=0))
    result["confusion_matrix_tn_fp_fn_tp"] = (
        confusion_matrix(predictions.label, alert, labels=[0, 1]).ravel().tolist()
    )
    result["event_window_coverage"] = coverage
    result["event_scope"] = "Selected machines only; complete preceding prediction windows"
    return result


def summarize_timings(batches: list[dict[str, float]]) -> dict[str, Any]:
    if not batches:
        raise ValueError("No measured inference batches")
    total_rows = int(sum(batch["rows"] for batch in batches))
    totals = np.array([batch["total_seconds"] for batch in batches])
    forwards = np.array([batch["sdk_predict_seconds"] for batch in batches])
    neural = [batch.get("neural_forward_seconds") for batch in batches]
    return {
        "batches": len(batches),
        "rows": total_rows,
        "total_prediction_seconds": float(totals.sum()),
        "sdk_predict_seconds": float(forwards.sum()),
        "neural_forward_seconds": sum(neural)
        if all(value is not None for value in neural)
        else None,
        "batch_total_ms_p50": float(np.median(totals) * 1000),
        "batch_total_ms_p95": float(np.quantile(totals, 0.95) * 1000),
        "batch_sdk_ms_p50": float(np.median(forwards) * 1000),
        "rows_per_second_total": total_rows / float(totals.sum()),
        "timing_scope": "SDK predict includes its cached preprocessing and postprocessing; "
        "not an isolated neural kernel forward pass",
    }
