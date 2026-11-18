"""Small artifact utilities; JSON never emits nonstandard NaN/Infinity values."""

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def verify_artifacts(run_dir: Path, filenames: list[str] | None = None) -> None:
    """Verify accidental drift against a run manifest (not a cryptographic trust signature)."""
    manifest_path = run_dir / "artifact_manifest.json"
    if not manifest_path.exists():
        return  # Training writes the manifest after its first evaluation.
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    for filename in filenames if filenames is not None else expected:
        if filename not in expected or sha256(run_dir / filename) != expected[filename]:
            raise ValueError(f"Experiment artifact changed: {filename}")
