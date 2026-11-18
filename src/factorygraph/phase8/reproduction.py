"""Prepare fresh reproductions of the fixed accepted candidate, without overwrites."""

import sys
from pathlib import Path

from factorygraph.io import sha256
from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase8.common import ROOT

ACCEPTED = Path("artifacts/phase8/study")


def prepare():
    if ROOT.resolve() == ACCEPTED.resolve():
        raise ValueError("Use a fresh FACTORYGRAPH_PHASE8_RUN_DIR")
    read_json(ROOT / "registration.json")
    save_new(ROOT / "harness_amendment.json", read_json(ACCEPTED / "harness_amendment.json"))
    return {"status": "fixed_corrected_controls_prepared", "run_dir": str(ROOT)}


def freeze():
    if ROOT.resolve() == ACCEPTED.resolve():
        raise ValueError("Cannot replace original candidate registration")
    read_json(ROOT / "baseline_profile_corrected/requests.json")
    record = read_json(ACCEPTED / "candidate_registration.json")
    candidate = "src/factorygraph/phase8/candidate.py"
    if sha256(Path(candidate)) != record["implementation_sha256"][candidate]:
        raise ValueError("Accepted optimization changed; requires a new study")
    record["reproduction_of_candidate_registration_sha256"] = sha256(
        ACCEPTED / "candidate_registration.json"
    )
    record["implementation_sha256"] = {
        p.as_posix(): sha256(p) for p in Path("src/factorygraph/phase8").glob("*.py")
    }
    save_new(ROOT / "candidate_registration.json", record)
    return {"status": "fixed_candidate_identity_registered", "run_dir": str(ROOT)}


if __name__ == "__main__":
    print(prepare() if sys.argv[1] == "prepare" else freeze())
