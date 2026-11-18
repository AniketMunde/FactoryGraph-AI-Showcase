"""Independent gated Phase 5 execution; failures remain reviewable."""

import argparse
import json
import logging
from pathlib import Path

from factorygraph.io import write_json
from factorygraph.phase5.analysis import analyze
from factorygraph.phase5.assembly import assemble
from factorygraph.phase5.common import audit, load_config
from factorygraph.phase5.contribution import inspect as contribution
from factorygraph.phase5.efficiency import measure
from factorygraph.phase5.learning import register_ablations, smoke, train
from factorygraph.phase5.relational import export as relational_export
from factorygraph.phase5.temporal import export, forecast, pilot, register
from factorygraph.phase5.verification import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=[
            "audit",
            "register",
            "pilot",
            "forecast",
            "temporal",
            "relational",
            "assemble",
            "smoke",
            "register-ablations",
            "train",
            "analyze",
            "verify",
            "efficiency",
            "contribution",
        ],
    )
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    config = load_config()
    if args.run_dir:
        config.run_dir = args.run_dir
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = {
            "audit": audit,
            "register": register,
            "pilot": pilot,
            "forecast": forecast,
            "temporal": export,
            "relational": relational_export,
            "assemble": assemble,
            "smoke": smoke,
            "register-ablations": register_ablations,
            "train": train,
            "analyze": analyze,
            "verify": verify,
            "efficiency": measure,
            "contribution": contribution,
        }[args.stage](config)
        print(json.dumps({"stage": args.stage, "status": result.get("status", "registered")}))
    except Exception as exc:
        write_json(
            config.run_dir / f"{args.stage}_failure.json",
            {"type": type(exc).__name__, "message": str(exc), "status": "incomplete"},
        )
        raise


if __name__ == "__main__":
    main()
