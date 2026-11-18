"""Additive console milestone: freeze accepted closure/research evidence without rewriting it."""

import argparse
from pathlib import Path

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase6.evaluation import graph_integrity
from factorygraph.phase6.integrity import prediction_parity, verify_mapping


def audit(root):
    if root.exists():
        raise ValueError("Use a fresh evidence directory")
    previous = Path("artifacts/phase7_closure/study")
    protected = read_json(previous / "protected.json")
    for name, change in read_json(previous / "source_amendments.json").items():
        assert protected[name] == change["before"]
        assert sha256(Path(change["backup"])) == change["before"]
        protected[name] = change["after"]
    protected.update(read_json(previous / "file_inventory.json"))
    protected["artifacts/phase7_closure/study/artifact_manifest.json"] = sha256(
        previous / "artifact_manifest.json"
    )
    for name, record in read_json(previous / "artifact_manifest.json").items():
        protected[(previous / name).as_posix()] = record["sha256"]
    verify_mapping(Path("."), protected)
    save_new(root / "protected.json", protected)
    save_new(
        root / "registration.json",
        {
            "date": "2026-11-16",
            "scope": "Operations Console v2; additive frontend milestone, no ML phase",
            "protected_files": len(protected),
            "graph": graph_integrity(),
            "baseline_A0_parity": prediction_parity(),
            "policy": {"threshold": 0.9996602309282403, "cooldown_hours": 24},
            "backend": "Original B, authenticated API v1, unchanged",
            "binding": "localhost:18601, loopback only",
            "authentication": "Separate local console passwords, opaque server-side sessions",
            "public_hosting": False,
        },
    )
    print({"status": "PASS", "protected_files": len(protected)})


def verify(root):
    verify_mapping(Path("."), read_json(root / "protected.json"))
    registration = read_json(root / "registration.json")
    assert graph_integrity() == registration["graph"]
    assert prediction_parity() == registration["baseline_A0_parity"]
    save_new(root / "preservation.json", {"status": "PASS", **registration})
    print({"preservation": "PASS", "protected_files": registration["protected_files"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["audit", "verify"])
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    globals()[args.stage](args.run_dir)
