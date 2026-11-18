"""Offline Phase 6 commands; JSON cases and separate immutable evaluator artifacts."""

import argparse
import json
import sys
import time
from pathlib import Path

from factorygraph.phase6.common import load_config, save_new


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    for stage in [
        "audit",
        "register",
        "fixtures",
        "integrate",
        "case",
        "fleet",
        "study",
        "evaluate",
    ]:
        command = sub.add_parser(stage)
        command.add_argument("--config", type=Path, default=Path("configs/phase6/v1.yaml"))
        command.add_argument("--run-dir", type=Path)
        if stage in {"case", "fleet"}:
            command.add_argument("--snapshot", required=True)
            command.add_argument("--output", type=Path)
        if stage == "case":
            command.add_argument("--machine", required=True, type=int)
        if stage == "fleet":
            command.add_argument("--machines", nargs="+", type=int)
    args = parser.parse_args()
    config = load_config(args.config, args.run_dir)
    root = Path("artifacts/phase6").resolve()
    if not config.run_dir.resolve().is_relative_to(root):
        parser.error("Phase 6 run directory must remain under artifacts/phase6")
    try:
        if args.stage == "audit":
            from factorygraph.phase6.integrity import protect

            result = protect(config)
        elif args.stage == "register":
            from factorygraph.phase6.integrity import register

            result = register(config)
        elif args.stage in {"fixtures", "integrate"}:
            from factorygraph.phase6.evaluation import test_gate

            result = test_gate(config, "c" if args.stage == "fixtures" else "d")
        elif args.stage == "study":
            from factorygraph.phase6.evaluation import study

            result = study(config)
        elif args.stage == "evaluate":
            from factorygraph.phase6.evaluation import OfflineEvaluationHarness

            result = OfflineEvaluationHarness(config).run()
        else:
            from factorygraph.phase6.service import CaseReportBuilder

            with CaseReportBuilder(config) as service:
                result = (
                    service.build(args.machine, args.snapshot)
                    if args.stage == "case"
                    else service.fleet(args.snapshot, args.machines)
                )
            if args.output:
                if not args.output.resolve().is_relative_to(root):
                    raise ValueError("Case output must remain under artifacts/phase6")
                save_new(args.output, result)
        print(json.dumps(result, indent=2, allow_nan=False))
    except Exception as error:
        record = {
            "status": "failed",
            "stage": args.stage,
            "error_type": type(error).__name__,
            "detail": str(error),
        }
        save_new(config.run_dir / "failures" / f"{args.stage}-{time.time_ns()}.json", record)
        print(json.dumps(record), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
