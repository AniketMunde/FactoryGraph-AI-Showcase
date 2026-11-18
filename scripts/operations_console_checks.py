"""Record actual frontend commands in fresh evidence files, with no secret build environment."""

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

from factorygraph.phase6.common import save_new

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["build", "security"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    node = Path(shutil.which("node"))
    npm = node.parent / "node_modules/npm/bin/npm-cli.js"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FG7_", "FG_CONSOLE_", "FACTORYGRAPH_"))
    }
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    commands = ["typecheck", "build"] if args.stage == "build" else ["test"]
    passed = True
    for name in commands:
        tick = time.perf_counter()
        command = [str(node), str(npm), "run", name]
        result = subprocess.run(
            command,
            cwd="apps/factorygraph_console",
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        save_new(
            args.run_dir / (name + ".json"),
            {
                "command": command,
                "returncode": result.returncode,
                "seconds": time.perf_counter() - tick,
                "output": result.stdout + result.stderr,
            },
        )
        passed = passed and result.returncode == 0
    print({"stage": args.stage, "passed": passed})
    if not passed:
        raise SystemExit(1)
