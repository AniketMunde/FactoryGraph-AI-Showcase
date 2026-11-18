"""Phase 7 preservation and minimal deployment inventory; never rewrite old artifacts."""

import json
import shutil
from pathlib import Path

from factorygraph.io import sha256, verify_artifacts, write_json
from factorygraph.phase6.common import POLICIES, read_json, save_new
from factorygraph.phase6.integrity import verify_mapping

ROOT = Path("artifacts/phase7")


def audit():
    if (ROOT / "protected.json").exists():
        raise ValueError("Phase 7 audit exists; use verify instead of replacing protection")
    verify_mapping(Path("."), read_json("artifacts/phase6/study/protected.json"))
    verify_artifacts(Path("artifacts/phase6/study"))
    paths = set(read_json("artifacts/phase6/study/protected.json"))
    for prefix in [
        "src/factorygraph/phase6",
        "tests/phase6",
        "configs/phase6",
        "docs/examples/phase6",
        "artifacts/phase6",
    ]:
        paths.update(
            p.as_posix()
            for p in Path(prefix).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
    paths.update(p.as_posix() for p in Path("docs").glob("PHASE6_*.md"))
    paths.update(
        ["docs/results/phase6.json", "requirements/phase6.lock", "scripts/phase6_verify.py"]
    )
    save_new(ROOT / "protected.json", {p: sha256(Path(p)) for p in sorted(paths)})
    return {
        "status": "passed",
        "protected_files": len(paths),
        "docker_available": shutil.which("docker") is not None,
    }


def verify():
    expected = read_json(ROOT / "protected.json")
    verify_mapping(Path("."), expected)
    return len(expected)


def inventory():
    record = read_json("artifacts/phase6/study/registration.json")
    paths = set(record["inputs_sha256"]) | set(POLICIES)
    paths.add("artifacts/phase6/study/registration.json")
    gallery = read_json("docs/examples/phase6/manifest.json")
    paths.add("docs/examples/phase6/manifest.json")
    paths.update(r["path"] for r in gallery.values())
    files = {}
    for name in sorted(paths):
        p = Path(name)
        category = "configuration_or_manifest"
        if p.suffix == ".csv":
            category = "source_csv"
        elif "temporal_c_" in name:
            category = "temporal_context"
        elif "predictions.parquet" in name:
            category = "frozen_prediction"
        elif p.suffix == ".parquet":
            category = "processed_parquet_or_membership"
        elif p.name == "model.txt":
            category = "approved_model_identity"
        elif p.name == "calibration.json":
            category = "calibration_identity"
        elif "examples/" in name:
            category = "verified_gallery"
        files[name] = {"sha256": sha256(p), "bytes": p.stat().st_size, "category": category}
    output = {
        "files": files,
        "bytes": sum(r["bytes"] for r in files.values()),
        "graph": read_json("artifacts/phase4/full/build.json"),
        "excluded": [
            "neural checkpoints",
            "CUDA/PyTorch",
            "unrelated experiments",
            "virtual environments",
            "credentials",
            "future evaluator outcomes in HTTP output",
        ],
        "hosted_redistribution_approved": False,
    }
    save_new(ROOT / "deployment_manifest.json", output)
    return output


def bundle():
    """Copy only inventoried inputs into a new ignored deployment staging directory."""
    data = read_json(ROOT / "deployment_manifest.json")
    target = ROOT / "runtime"
    if target.exists():
        raise ValueError("Runtime staging exists; refuse overwrite")
    for name, record in data["files"].items():
        if sha256(Path(name)) != record["sha256"]:
            raise ValueError("Runtime input changed")
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, dest)
    write_json(target / "deployment_manifest.json", data)
    return {"files": len(data["files"]), "bytes": data["bytes"]}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["audit", "inventory", "bundle", "verify"])
    args = parser.parse_args()
    result = globals()[args.stage]()
    print(
        json.dumps(
            result
            if args.stage != "inventory"
            else {"files": len(result["files"]), "bytes": result["bytes"]}
        )
    )
