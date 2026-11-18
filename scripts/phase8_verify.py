"""Capture fresh real regression/package command evidence without rewriting Phase 7."""

import argparse
import os
import subprocess
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from factorygraph.phase6.common import save_new
from factorygraph.phase8.common import ROOT


def command(args, env=None):
    tick = time.perf_counter()
    p = subprocess.run(args, env=env, capture_output=True, text=True)
    return {
        "command": args,
        "returncode": p.returncode,
        "seconds": time.perf_counter() - tick,
        "output": p.stdout + p.stderr,
    }


def environment(name):
    exe = str(Path(".venv" if name == "base" else ".venv-" + name) / "Scripts/python.exe")
    env = os.environ.copy()
    for key in [
        "FACTORYGRAPH_NEO4J_INTEGRATION",
        "FACTORYGRAPH_PHASE7_INTEGRATION",
        "FACTORYGRAPH_PHASE7_HTTP",
        "FACTORYGRAPH_PHASE8_INTEGRATION",
    ]:
        env.pop(key, None)
    if name in {"phase4", "phase7"}:
        env["FACTORYGRAPH_NEO4J_INTEGRATION"] = "1"
    if name == "phase7":
        for key in [
            "FACTORYGRAPH_PHASE7_INTEGRATION",
            "FACTORYGRAPH_PHASE7_HTTP",
            "FACTORYGRAPH_PHASE8_INTEGRATION",
        ]:
            env[key] = "1"
    tests = command([exe, "-m", "pytest", "-q"], env)
    dependencies = command([exe, "-m", "pip", "check"], env)
    save_new(ROOT / "regressions" / (name + ".json"), tests)
    save_new(ROOT / "regressions" / (name + "-dependencies.json"), dependencies)
    return name, {
        "returncode": tests["returncode"],
        "summary": tests["output"].splitlines()[-1:],
        "seconds": tests["seconds"],
        "dependency_returncode": dependencies["returncode"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-name", choices=["final"])
    args = parser.parse_args()
    if args.evidence_name:
        ROOT = ROOT / args.evidence_name
    if (ROOT / "test_results.json").exists():
        raise ValueError("Actual evidence already exists; refuse overwrite")
    with ThreadPoolExecutor(max_workers=5) as pool:
        tests = dict(pool.map(environment, ["base", "phase2", "phase3", "phase4", "phase7"]))
    save_new(ROOT / "test_results.json", tests)
    exe = str(Path(".venv-phase7/Scripts/python.exe"))
    checks = {
        "lint": command([exe, "-m", "ruff", "check", "."]),
        "format": command([exe, "-m", "ruff", "format", "--check", "."]),
        "build": command([exe, "-m", "build", "--no-isolation", "--outdir", str(ROOT / "dist")]),
    }
    wheel = next((ROOT / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel) as package:
        modules = {
            "factorygraph/phase8/" + p.name for p in Path("src/factorygraph/phase8").glob("*.py")
        }
        assert modules <= set(package.namelist())
    passed = all(
        r["returncode"] == r["dependency_returncode"] == 0 for r in tests.values()
    ) and all(r["returncode"] == 0 for r in checks.values())
    save_new(
        ROOT / "release_checks.json",
        {
            "passed": passed,
            "commands": checks,
            "wheel_phase8_modules": len(modules),
            "docker": "not_executed",
        },
    )
    print({"tests": tests, "passed": passed})
