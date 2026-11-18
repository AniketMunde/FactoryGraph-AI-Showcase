"""Current regression evidence for closure, without rewriting accepted reports/results."""

import argparse
import os
import subprocess
import time
from pathlib import Path

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new


def command(args, env=None):
    tick = time.perf_counter()
    p = subprocess.run(args, capture_output=True, text=True, env=env)
    return {
        "command": args,
        "returncode": p.returncode,
        "seconds": time.perf_counter() - tick,
        "output": p.stdout + p.stderr,
    }


def environment(name, root):
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
    r = command([exe, "-m", "pytest", "-q"], env)
    d = command([exe, "-m", "pip", "check"], env)
    save_new(root / "regressions" / (name + ".json"), r)
    save_new(root / "regressions" / (name + "-dependencies.json"), d)
    return name, {
        "returncode": r["returncode"],
        "dependency_returncode": d["returncode"],
        "summary": r["output"].splitlines()[-1:],
        "seconds": r["seconds"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prior-evidence", type=Path)
    parser.add_argument("--environments", nargs="+", default=None)
    args = parser.parse_args()
    root = args.run_dir
    if (root / "test_results.json").exists():
        raise ValueError("Evidence exists; preserve command logs")
    names = ["base", "phase2", "phase3", "phase4", "phase7"]
    rerun = args.environments or names
    assert set(rerun) <= set(names)
    tests, reused = {}, {}
    for name in names:
        if name in rerun:
            _, tests[name] = environment(name, root)
        else:
            assert args.prior_evidence is not None
            previous = read_json(args.prior_evidence / "test_results.json")[name]
            assert previous["returncode"] == previous["dependency_returncode"] == 0
            tests[name] = previous
            reused[name] = {}
            for suffix in ["", "-dependencies"]:
                source = args.prior_evidence / "regressions" / (name + suffix + ".json")
                save_new(root / "regressions" / source.name, read_json(source))
                reused[name][source.as_posix()] = sha256(source)
    save_new(root / "evidence_reuse.json", reused)
    save_new(root / "test_results.json", tests)
    exe = str(Path(".venv-phase7/Scripts/python.exe"))
    checks = {
        "ruff": command([exe, "-m", "ruff", "check", "."]),
        "format": command([exe, "-m", "ruff", "format", "--check", "."]),
        "build": command([exe, "-m", "build", "--no-isolation", "--outdir", str(root / "dist")]),
    }
    browser_exe = str(Path("artifacts/phase7_closure/browser-venv/Scripts/python.exe"))
    checks["browser_dependencies"] = command([browser_exe, "-m", "pip", "check"])
    passed = all(
        r["returncode"] == r["dependency_returncode"] == 0 for r in tests.values()
    ) and all(r["returncode"] == 0 for r in checks.values())
    save_new(
        root / "release_checks.json",
        {"passed": passed, "commands": checks, "container_execution": "BLOCKED_no_Docker"},
    )
    print({"tests": tests, "checks_passed": passed})
