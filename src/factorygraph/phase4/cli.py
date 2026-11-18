"""Phase 4 gated local research commands; never trains predictive models."""

import argparse
import json
from pathlib import Path

from factorygraph.io import write_json
from factorygraph.phase4.config import load_config
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.features import export_features
from factorygraph.phase4.queries import EvidenceRequest, HistoricalQueries
from factorygraph.phase4.source import audit
from factorygraph.phase4.study import benchmark, build, register, validate_queries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=[
            "audit",
            "register",
            "pilot",
            "build",
            "validate",
            "benchmark",
            "export",
            "evidence",
        ],
    )
    parser.add_argument("--config", type=Path, default=Path("configs/phase4/full.yaml"))
    parser.add_argument("--machine", type=int, default=17)
    parser.add_argument("--cutoff", default="2015-10-15T00:00:00Z")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        if args.stage == "audit":
            result = audit(config)
        elif args.stage == "register":
            result = register(config)
        elif args.stage in {"pilot", "build"}:
            result = build(config, pilot=args.stage == "pilot")
        else:
            db = GraphDB(config)
            try:
                if args.stage == "validate":
                    result = validate_queries(db, config)
                elif args.stage == "benchmark":
                    result = benchmark(db, config)
                elif args.stage == "export":
                    result = export_features(db, config)
                else:
                    result = HistoricalQueries(db).neighborhood(
                        EvidenceRequest(machine_id=args.machine, cutoff=args.cutoff)
                    )
            finally:
                db.close()
        if args.stage == "evidence":
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps({"stage": args.stage, "status": result.get("status", "registered")}))
    except Exception as exc:
        config.run_dir.mkdir(parents=True, exist_ok=True)
        # Connection exceptions can include user/URI but never serialize authentication tokens.
        write_json(
            config.run_dir / f"{args.stage}_failure.json",
            {"status": "incomplete", "type": type(exc).__name__, "message": str(exc)},
        )
        raise


if __name__ == "__main__":
    main()
