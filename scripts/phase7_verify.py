"""Current command evidence for all environments and the native Phase 7 demo."""

import argparse
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from factorygraph.phase6.common import save_new

ROOT = Path("artifacts/phase7")


def command(argv, env=None):
    started = time.perf_counter()
    p = subprocess.run(argv, env=env, capture_output=True, text=True)
    return {
        "command": argv,
        "returncode": p.returncode,
        "seconds": time.perf_counter() - started,
        "output": p.stdout + p.stderr,
    }


def environment_test(name):
    directory = ".venv" if name == "base" else ".venv-" + name
    exe = str(Path(directory) / "Scripts/python.exe")
    env = os.environ.copy()
    for key in [
        "FACTORYGRAPH_NEO4J_INTEGRATION",
        "FACTORYGRAPH_PHASE7_INTEGRATION",
        "FACTORYGRAPH_PHASE7_HTTP",
    ]:
        env.pop(key, None)
    if name in {"phase4", "phase7"}:
        env["FACTORYGRAPH_NEO4J_INTEGRATION"] = "1"
    if name == "phase7":
        env["FACTORYGRAPH_PHASE7_INTEGRATION"] = "1"
        env["FACTORYGRAPH_PHASE7_HTTP"] = "1"
    result = command([exe, "-m", "pytest", "-q"], env)
    save_new(ROOT / "regressions" / f"{name}.json", result)
    check = command([exe, "-m", "pip", "check"], env)
    save_new(ROOT / "regressions" / f"{name}-dependencies.json", check)
    return name, {
        "returncode": result["returncode"],
        "seconds": result["seconds"],
        "summary": result["output"].splitlines()[-1:],
        "dependency_returncode": check["returncode"],
    }


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-name", choices=["final"])
    args = parser.parse_args()
    if args.evidence_name:
        ROOT = ROOT / args.evidence_name
    if (ROOT / "test_results.json").exists():
        raise ValueError("Verification exists; preserve the actual command evidence")
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(pool.map(environment_test, ["base", "phase2", "phase3", "phase4", "phase7"]))
    save_new(ROOT / "test_results.json", results)
    base = str(Path(".venv-phase7/Scripts/python.exe"))
    checks = {
        "ruff": command([base, "-m", "ruff", "check", "."]),
        "format": command([base, "-m", "ruff", "format", "--check", "."]),
        "build": command([base, "-m", "build", "--no-isolation", "--outdir", str(ROOT / "dist")]),
    }
    import zipfile

    wheel = next((ROOT / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel) as package:
        modules = {
            "factorygraph/phase7/" + p.name for p in Path("src/factorygraph/phase7").glob("*.py")
        }
        assert modules <= set(package.namelist())
    import importlib.util

    assert importlib.util.find_spec("torch") is None
    passed = all(
        r["returncode"] == 0 and r["dependency_returncode"] == 0 for r in results.values()
    ) and all(r["returncode"] == 0 for r in checks.values())
    save_new(
        ROOT / "release_checks.json",
        {
            "passed": passed,
            "commands": checks,
            "wheel_phase7_modules": len(modules),
            "no_torch": True,
            "docker_execution": "not_executed_unavailable",
        },
    )
    print({"tests": results, "passed": passed})


if __name__ == "__main__":
    main()
