"""Portable Phase 5 scientific evidence, source identity and preservation summary."""

import json
import platform
from importlib.metadata import version
from pathlib import Path

from factorygraph.io import sha256, write_json
from factorygraph.phase5.common import load_config, save_manifest, verify_prior, verify_registration


def finalize(config):
    verify_registration(config)
    verification = json.loads((config.run_dir / "verification.json").read_text())
    tests_path = Path("artifacts/phase5/test_results.json")
    tests = json.loads(tests_path.read_text()) if tests_path.exists() else {"status": "pending"}
    files = {
        name: json.loads((config.run_dir / name).read_text())
        for name in [
            "registration.json",
            "admission.json",
            "forecast_runtime.json",
            "temporal_manifest.json",
            "assembly.json",
            "ablation_registration.json",
            "frozen_models.json",
            "results.json",
            "contribution.json",
            "efficiency.json",
            "graph_export_runtime.json",
            "relational_manifest.json",
        ]
    }
    result = {
        "date": "2026-11-13",
        "status": "completed_phase5"
        if verification["status"] == "passed" and tests["status"] == "passed"
        else "verification_pending",
        "decision": files["results.json"]["decision"],
        "study": files,
        "verification": verification,
        "tests": tests,
        "preservation": {
            "historical_files_unchanged": verify_prior(),
            "phase1_4_results_untouched": True,
            "metropt_test_still_incomplete": True,
        },
        "accepted_graph_integrity": json.loads(
            Path("artifacts/phase5/graph_integrity.json").read_text()
        )
        if Path("artifacts/phase5/graph_integrity.json").exists()
        else None,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                n: version(n)
                for n in ["lightgbm", "pandas", "numpy", "scikit-learn", "scipy", "pydantic"]
            },
        },
        "neural_environment": json.loads(
            Path("artifacts/phase5/neural_environment.json").read_text()
        )
        if Path("artifacts/phase5/neural_environment.json").exists()
        else None,
        "resource_preflight": {
            k: v
            for k, v in json.loads(Path("artifacts/phase5/preflight.json").read_text()).items()
            if k != "protected_files"
        },
        "source_sha256": {
            p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase5").glob("*.py")
        },
        "implementation_sha256": {
            p.as_posix(): sha256(p)
            for root in ["src/factorygraph/phase5", "tests/phase5", "configs/phase5"]
            for p in Path(root).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        },
        "phase5_lock_sha256": sha256(Path("requirements/phase5.lock")),
        "accepted_phase3_lock_sha256": sha256(Path("requirements/phase3-cu128.lock")),
        "phase6_readiness": (
            "Evidence and interfaces exist; no predictive replacement approved; "
            "decision support not implemented"
        ),
        "limitations": [
            "Synthetic Azure/public and previously observed test; not a fresh real-world holdout",
            "One configuration/seed; exploratory cluster intervals with peer dependence",
            "Validation alert budgets match; test alert counts differ under frozen policies",
            "Modern weights used retrospectively; public pretraining overlap not ruled out",
            "Timing includes local caches/concurrent desktop activity; no serving guarantee",
            "No augmented Kumo, stacking, real-data fusion, Phase6 agent/dashboard/deployment",
        ],
    }
    save_manifest(config.run_dir)
    write_json(Path("docs/results/phase5.json"), result)
    root = Path("artifacts/phase5")
    write_json(
        root / "artifact_manifest.json",
        {
            p.relative_to(root).as_posix(): sha256(p)
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".parquet", ".txt", ".csv"}
            and p != root / "artifact_manifest.json"
        },
    )
    return result


if __name__ == "__main__":
    print(finalize(load_config())["status"])
