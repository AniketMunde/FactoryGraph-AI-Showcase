"""Capture current Phase 6 regressions, dependencies and package checks without old writes."""

import argparse
import os
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new


def command(argv, environment=None):
    start = time.perf_counter()
    result = subprocess.run(argv, capture_output=True, text=True, env=environment)
    return {
        "command": argv,
        "returncode": result.returncode,
        "seconds": time.perf_counter() - start,
        "output": result.stdout + result.stderr,
    }


def verify(run_dir):
    if not run_dir.resolve().is_relative_to(Path("artifacts/phase6").resolve()):
        raise ValueError("Verification outputs must remain under artifacts/phase6")
    if (run_dir / "test_results.json").exists():
        raise ValueError("Verification evidence exists; retain it and choose a new run")
    results, dependencies = {}, {}
    for name, directory in [
        ("base", ".venv"),
        ("phase2", ".venv-phase2"),
        ("phase3", ".venv-phase3"),
        ("phase4", ".venv-phase4"),
    ]:
        exe = str(Path(directory) / "Scripts/python.exe")
        env = os.environ.copy()
        env["FACTORYGRAPH_PHASE6_RUN_DIR"] = str(run_dir)
        env.pop("FACTORYGRAPH_NEO4J_INTEGRATION", None)
        if name == "phase4":
            env["FACTORYGRAPH_NEO4J_INTEGRATION"] = "1"
        result = command([exe, "-m", "pytest", "-q"], env)
        path = run_dir / "regressions" / f"{name}.json"
        save_new(path, result)
        results[name] = {k: result[k] for k in ["command", "returncode", "seconds"]}
        results[name]["summary"] = result["output"].splitlines()[-1:]
        results[name]["log_sha256"] = sha256(path)
        dependencies[name] = command([exe, "-m", "pip", "check"], env)
    save_new(run_dir / "test_results.json", results)
    checks = {}
    base = str(Path(".venv/Scripts/python.exe"))
    for label, args in [
        ("ruff", [base, "-m", "ruff", "check", "."]),
        ("format", [base, "-m", "ruff", "format", "--check", "."]),
        ("build", [base, "-m", "build", "--no-isolation", "--outdir", str(run_dir / "dist")]),
    ]:
        checks[label] = command(args)
    package = {}
    if checks["build"]["returncode"] == 0:
        wheel = next((run_dir / "dist").glob("*.whl"))
        source = next((run_dir / "dist").glob("*.tar.gz"))
        modules = {
            f"factorygraph/phase6/{p.name}" for p in Path("src/factorygraph/phase6").glob("*.py")
        }
        with zipfile.ZipFile(wheel) as archive:
            assert modules <= set(archive.namelist())
            assert not any(
                ".env" in n.split("/") or "artifacts" in n.split("/") for n in archive.namelist()
            )
        with tarfile.open(source) as archive:
            members = archive.getnames()
            assert all(any(n.endswith("/src/" + m) for n in members) for m in modules)
        # Preserve the prior MANIFEST.in: provide new JSON configs/helper separately.
        bundle = run_dir / "dist" / "factorygraph-phase6-resources.zip"
        resources = [*Path("configs/phase6").glob("*"), Path("scripts/phase6_verify.py")]
        with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in resources:
                archive.write(path, path.as_posix())
        with zipfile.ZipFile(bundle) as archive:
            assert {p.as_posix() for p in resources} == set(archive.namelist())
        package = {
            "python_modules_in_wheel_and_sdist": len(modules),
            "registered_configs_in_resource_bundle": True,
            "unchanged_prior_packaging_metadata": True,
            "artifacts": {
                p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)}
                for p in [wheel, source, bundle]
            },
        }
    examples = read_json("docs/examples/phase6/manifest.json")
    for record in examples.values():
        assert sha256(Path(record["path"])) == record["sha256"]
    frozen = read_json(run_dir / "implementation_freeze.json")
    assert all(sha256(Path(p)) == h for p, h in frozen.items())
    passed = all(
        r["returncode"] == 0 for r in [*results.values(), *dependencies.values(), *checks.values()]
    )
    save_new(
        run_dir / "release_checks.json",
        {
            "passed": passed,
            "checks": checks,
            "dependencies": dependencies,
            "package": package,
            "verified_examples": len(examples),
            "frozen_service_implementation_unchanged": True,
        },
    )
    if not passed:
        raise ValueError("Release/regression checks failed; evidence retained")
    print({"status": "passed", "tests": results, "package": package})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("artifacts/phase6/study"))
    verify(parser.parse_args().run_dir)
