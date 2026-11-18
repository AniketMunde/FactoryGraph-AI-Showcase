"""Explicit register/download/smoke/run stages for the Phase 2 study."""

import argparse
import json
import logging
from pathlib import Path

from factorygraph.io import write_json
from factorygraph.phase2.adapter import ModelInferenceError, ModelLoadError, download_checkpoint
from factorygraph.phase2.config import load_config
from factorygraph.phase2.inputs import register
from factorygraph.phase2.runner import run, smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="FactoryGraph Phase 2 pretrained tabular study")
    parser.add_argument("stage", choices=["register", "download", "smoke", "run"])
    parser.add_argument("--config", type=Path, default=Path("configs/phase2/kumo_pilot.yaml"))
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    config = load_config(args.config)
    if args.run_dir:
        config.run_dir = args.run_dir
    try:
        if args.stage == "register":
            value = register(config)
            print(json.dumps({"machines": value["machines"], "rows": value["query_rows"]}))
        elif args.stage == "download":
            download_checkpoint(config)
        elif args.stage == "smoke":
            value = smoke(config)
            print(
                json.dumps(
                    {
                        name: value[name]
                        for name in [
                            "status",
                            "projected_pilot_seconds_with_margin",
                            "projected_full_fleet_seconds_with_margin",
                        ]
                    },
                    indent=2,
                )
            )
        else:
            value = run(config)
            print(
                json.dumps(
                    {
                        "status": value["status"],
                        "policy": value["selected_policy"],
                        "test_average_precision": {
                            name: result["pr_auc_average_precision"]
                            for name, result in value["test"].items()
                        },
                    },
                    indent=2,
                )
            )
    except (ValueError, OSError, RuntimeError, ModelLoadError, ModelInferenceError) as exc:
        if config.run_dir.exists():
            write_json(
                config.run_dir / f"{args.stage}_failure.json",
                {
                    "status": "incomplete",
                    "stage": args.stage,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        parser.exit(1, f"Phase 2 {args.stage} failed: {exc}\n")


if __name__ == "__main__":
    main()
