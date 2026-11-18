"""Causal robust and previously-issued forecast residual scores; no failure annotations."""

from typing import Any

import numpy as np
import pandas as pd

from factorygraph.phase3.sequences import robust_scale


def robust_observation_scores(
    sequences: dict[int, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp, length: int
) -> pd.DataFrame:
    frames = []
    for machine, sequence in sequences.items():
        index = pd.date_range(start - pd.Timedelta(hours=length), end, freq="h", inclusive="left")
        data = sequence.reindex(index)
        for channel in data.columns:
            values = data[channel].to_numpy(dtype=float)
            contexts = np.lib.stride_tricks.sliding_window_view(values, length)[:-1]
            actual = values[length:]
            median, scale = robust_scale(contexts)
            scores = np.abs(actual - median) / scale
            valid = np.isfinite(contexts).all(axis=1) & np.isfinite(actual)
            scores[~valid] = np.nan
            frames.append(
                pd.DataFrame(
                    {
                        "machineID": machine,
                        "channel": channel,
                        "observation_time": index[length:],
                        "source_max": index[length:],
                        "score": scores,
                        "method": "robust_mad",
                    }
                )
            )
    return pd.concat(frames, ignore_index=True)


def residual_scores(evaluation: pd.DataFrame, available_by: pd.Timestamp) -> pd.DataFrame:
    data = evaluation.loc[
        (evaluation.issue_time <= evaluation.target_time) & (evaluation.target_time <= available_by)
    ].copy()
    if not (data.source_observation_time < data.issue_time).all():
        raise ValueError("Forecast context contains future data")
    # Latest forecast per realized identity; forecast issue and actual availability are distinct.
    data = data.sort_values("issue_time").drop_duplicates(
        ["machineID", "target_time", "channel"], keep="last"
    )
    data["score"] = np.abs(data.actual - data.chronos) / data.context_robust_scale
    return data.rename(columns={"target_time": "observation_time"}).assign(
        method="forecast_residual", source_max=lambda frame: frame.observation_time
    )[["machineID", "channel", "observation_time", "source_max", "issue_time", "score", "method"]]


def fit_thresholds(scores: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    if (
        scores.empty
        or (scores.observation_time < start).any()
        or (scores.observation_time >= end).any()
    ):
        raise ValueError("Threshold fitting data must lie exclusively in validation")
    if (scores.source_max >= end).any():
        raise ValueError("Future observation entered threshold calibration")
    thresholds = {}
    for (method, channel), group in scores.groupby(["method", "channel"]):
        values = group.score.dropna().to_numpy()
        if not len(values):
            raise ValueError("No historical observations for threshold")
        thresholds[f"{method}:{channel}"] = float(np.quantile(values, 0.99, method="higher"))
    return {
        "thresholds": thresholds,
        "quantile": 0.99,
        "fit_start": start.isoformat(),
        "fit_end_exclusive": end.isoformat(),
        "source_max": scores.source_max.max().isoformat(),
        "interpretation": "Score exceedance thresholds, not validated failure/anomaly truth",
    }
