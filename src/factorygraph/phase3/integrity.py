"""Protection for all accepted data, artifacts, code, configurations, locks and reports."""

import json
from pathlib import Path

from factorygraph.io import sha256, verify_artifacts, write_json


def capture() -> dict[str, str]:
    for path in [Path("artifacts/baseline"), Path("artifacts/phase2/kumo-full")]:
        verify_artifacts(path)
    prior = json.loads(Path("docs/results/phase2.json").read_text())["results"]
    for filename, digest in {
        **prior["registration"]["protected_sha256"],
        **prior["environment"]["source_sha256"],
    }.items():
        if sha256(Path(filename)) != digest:
            raise ValueError(f"Accepted source or artifact changed: {filename}")
    paths = []
    for root in [
        "data/raw/azure",
        "data/processed/azure",
        "artifacts/baseline",
        "artifacts/phase2",
        "src/factorygraph/phase2",
        "configs/phase2",
    ]:
        paths.extend(
            p for p in Path(root).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    paths.extend(Path("src/factorygraph").glob("*.py"))
    paths.extend(
        Path(p)
        for p in [
            "requirements.lock",
            "requirements/phase2-cu128.lock",
            "docs/PHASE1_REPORT.md",
            "docs/PHASE2_REPORT.md",
            "docs/results/phase1.json",
            "docs/results/phase2.json",
            "configs/baseline.yaml",
        ]
    )
    return {p.as_posix(): sha256(p) for p in sorted(set(paths))}


def freeze(path: Path) -> None:
    if path.exists():
        verify(path)
    else:
        write_json(path, capture())


def verify(path: Path) -> None:
    for filename, digest in json.loads(path.read_text()).items():
        if sha256(Path(filename)) != digest:
            raise ValueError(f"Protected historical file changed: {filename}")
