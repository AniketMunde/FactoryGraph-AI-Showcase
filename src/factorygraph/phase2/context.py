"""Label availability, nested uniform context, and outcome-independent cohort selection."""

import hashlib

import numpy as np
import pandas as pd

KEYS = ["machineID", "datetime"]


def validate_keys(frame: pd.DataFrame) -> None:
    if any(name not in frame for name in KEYS):
        raise ValueError("Rows require machineID and datetime keys")
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise ValueError("Missing or duplicate query/context keys")
    if not isinstance(frame.datetime.dtype, pd.DatetimeTZDtype):
        raise ValueError("Timezone-aware query/context times are required")


def choose_context(train: pd.DataFrame, size: int, seed: int) -> pd.DataFrame:
    """Uniform sampling without replacement; prefix budgets are nested, no oversampling."""
    validate_keys(train)
    if size > len(train):
        raise ValueError("Context budget exceeds historical training rows")
    ordered = train.sort_values(KEYS).reset_index(drop=True)
    indices = np.random.default_rng(seed).permutation(len(ordered))[:size]
    context = ordered.iloc[indices].copy().reset_index(drop=True)
    if set(context.label.unique()) != {0, 1}:
        raise ValueError("Selected context must contain both binary classes")
    return context


def assert_context_eligible(
    context: pd.DataFrame, query: pd.DataFrame, horizon_hours: int = 24
) -> None:
    """Conservative outcome availability is the end of every context's label horizon."""
    validate_keys(context)
    validate_keys(query)
    if context.empty or query.empty:
        raise ValueError("Context and query must be nonempty")
    if "label_end" not in context or context.label_end.isna().any():
        raise ValueError("Context requires label availability timestamps")
    if not isinstance(context.label_end.dtype, pd.DatetimeTZDtype):
        raise ValueError("Label availability times require a timezone")
    if not (context.label_end == context.datetime + pd.Timedelta(hours=horizon_hours)).all():
        raise ValueError("Context label availability must include the complete prediction horizon")
    if context.label_end.max() >= query.datetime.min():
        raise ValueError("Context outcomes are not strictly available before every query")
    if not context.merge(query[KEYS], on=KEYS, how="inner").empty:
        raise ValueError("Context and query rows overlap")


def choose_machines(machine_ids: list[int], count: int, seed: int) -> list[int]:
    if count > len(machine_ids):
        raise ValueError("Cohort budget exceeds available machines")
    return sorted(
        sorted(
            machine_ids,
            key=lambda machine: hashlib.sha256(f"{seed}:{machine}".encode()).hexdigest(),
        )[:count]
    )


def pair_frozen_predictions(query: pd.DataFrame, frozen: pd.DataFrame) -> pd.DataFrame:
    """Left joins must preserve exactly the requested membership and labels."""
    validate_keys(query)
    validate_keys(frozen)
    paired = query[KEYS + ["label"]].merge(
        frozen,
        on=KEYS,
        how="left",
        suffixes=("", "_frozen"),
        validate="one_to_one",
        indicator=True,
    )
    if not (paired["_merge"] == "both").all():
        raise ValueError("Frozen baseline is missing query rows")
    if not (paired.label == paired.label_frozen).all():
        raise ValueError("Phase 1 target labels differ from query labels")
    return paired.drop(columns=["_merge", "label_frozen"])
