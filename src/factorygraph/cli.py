"""Independent acquisition, preparation, training, evaluation and inference commands."""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from factorygraph.config import load_config
from factorygraph.data import download, prepare
from factorygraph.inference import Predictor
from factorygraph.training import create_snapshots, evaluate_run, train


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="FactoryGraph AI Phase 1")
    parser.add_argument("command", choices=["download", "prepare", "train", "evaluate", "predict"])
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.yaml"))
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--input", type=Path, help="Precomputed causal feature Parquet for predict")
    parser.add_argument("--output", type=Path, help="Prediction output Parquet")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        config = load_config(args.config)
        if args.run_dir:
            config.run_dir = args.run_dir
        if args.command == "download":
            download(config.raw_dir)
        elif args.command == "prepare":
            create_snapshots(config, prepare(config.raw_dir, config.processed_dir))
        elif args.command == "train":
            train(config)
        elif args.command == "evaluate":
            metrics = evaluate_run(config.run_dir)
            print(json.dumps(metrics["test"], indent=2))
        else:
            if args.input is None or args.output is None:
                parser.error("predict requires --input and --output")
            frame = pd.read_parquet(args.input)
            predictor = Predictor(config.run_dir)
            result = frame[["machineID", "datetime"]].copy()
            result["probability"] = predictor.predict(frame)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            result.to_parquet(args.output, index=False)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
