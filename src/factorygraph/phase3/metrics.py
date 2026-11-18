"""Recomputable forecasting metrics on explicitly paired temporal identities."""

from typing import Any

import numpy as np
import pandas as pd

MODELS = ["chronos", "persistence", "rolling_mean", "seasonal_naive"]
IDENTITY = ["machineID", "issue_time", "target_time", "channel", "lead"]


def attach_actuals(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    if (
        forecasts.duplicated(IDENTITY).any()
        or actuals.duplicated(["machineID", "target_time", "channel"]).any()
    ):
        raise ValueError("Duplicate forecast or actual identities")
    result = forecasts.merge(
        actuals, on=["machineID", "target_time", "channel"], how="left", validate="many_to_one"
    )
    if not np.isfinite(result.actual.to_numpy()).all():
        raise ValueError("Incomplete forecast/actual matching")
    if not (result.target_time >= result.issue_time).all():
        raise ValueError("Forecast target precedes its issue time")
    return result


def point_metrics(actual: np.ndarray, prediction: np.ndarray, scale: np.ndarray) -> dict[str, Any]:
    error = actual - prediction
    valid = np.isfinite(scale) & (scale > 0)
    return {
        "count": len(error),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "mase": float(np.mean(np.abs(error[valid]) / scale[valid])) if valid.any() else None,
        "mase_valid_count": int(valid.sum()),
    }


def summarize(frame: pd.DataFrame, scales: pd.DataFrame) -> dict[str, Any]:
    data = frame.merge(scales, on=["machineID", "channel"], validate="many_to_one")
    output: dict[str, Any] = {}
    for horizon in [h for h in [3, 12, 24] if h <= data.lead.max()]:
        subset = data.loc[data.lead <= horizon]
        entry = {"by_channel": {}, "by_machine": {}}
        for channel, group in subset.groupby("channel"):
            metrics = {
                model: point_metrics(
                    group.actual.to_numpy(), group[model].to_numpy(), group.mase_scale.to_numpy()
                )
                for model in MODELS
            }
            errors = group.actual.to_numpy()[:, None] - group[["q10", "q50", "q90"]].to_numpy()
            levels = np.array([0.1, 0.5, 0.9])
            metrics["chronos"].update(
                pinball_loss=float(np.maximum(levels * errors, (levels - 1) * errors).mean()),
                interval_80_coverage=float(
                    ((group.actual >= group.q10) & (group.actual <= group.q90)).mean()
                ),
                interval_80_mean_width=float((group.q90 - group.q10).mean()),
            )
            entry["by_channel"][channel] = metrics
        for machine, group in subset.groupby("machineID"):
            # MASE allows a cross-channel aggregate; raw-unit MAE does not.
            entry["by_machine"][str(machine)] = {
                model: point_metrics(
                    group.actual.to_numpy(), group[model].to_numpy(), group.mase_scale.to_numpy()
                )["mase"]
                for model in MODELS
            }
        entry["macro_mase"] = {}
        for model in MODELS:
            valid = [
                values[model]["mase"]
                for values in entry["by_channel"].values()
                if values[model]["mase"] is not None
            ]
            entry["macro_mase"][model] = float(np.mean(valid)) if valid else None
        output[str(horizon)] = entry
    return output
