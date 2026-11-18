"""Fresh-process benchmark of the accepted CPU model; no fit or artifact writes."""

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

from factorygraph.inference import Predictor
from factorygraph.phase2.config import Phase2Config
from factorygraph.phase2.context import pair_frozen_predictions
from factorygraph.phase2.inputs import load_inputs, registered_queries, verify_registration
from factorygraph.phase2.metrics import summarize_timings


def benchmark(config: Phase2Config) -> dict[str, Any]:
    verify_registration(config)
    _, columns, splits, _ = load_inputs(config)
    test = registered_queries(config, splits["test"], "test")
    frozen = pd.read_parquet(config.baseline_dir / "test_predictions.parquet")
    start = time.perf_counter()
    predictor = Predictor(config.baseline_dir)
    load_seconds = time.perf_counter() - start
    predictor.predict(test.head(config.batch_size)[columns])
    batches = []
    for offset in range(0, len(test), config.batch_size):
        batch = test.iloc[offset : offset + config.batch_size]
        start = time.perf_counter()
        probabilities = predictor.predict(batch[columns])
        seconds = time.perf_counter() - start
        expected = pair_frozen_predictions(batch, frozen).probability.to_numpy()
        if not np.allclose(probabilities, expected, atol=1e-12, rtol=1e-10):
            raise RuntimeError("Saved baseline inference differs from frozen predictions")
        batches.append(
            {"rows": len(batch), "total_seconds": seconds, "sdk_predict_seconds": seconds}
        )
    memory = psutil.Process().memory_info()
    return {
        "model_load_seconds": load_seconds,
        "prediction": summarize_timings(batches),
        "rss_bytes": memory.rss,
        "peak_process_working_set_bytes": getattr(memory, "peak_wset", None),
        "scope": "Fresh CPU-only process; includes benchmark tables and Python libraries",
    }


if __name__ == "__main__":
    import sys

    config = Phase2Config.model_validate_json(Path(sys.argv[1]).read_text())
    print(json.dumps(benchmark(config), allow_nan=False))
