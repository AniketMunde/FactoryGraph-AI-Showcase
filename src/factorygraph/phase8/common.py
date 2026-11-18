"""Immutable Phase 8 registration, actual preflight and bounded resource checks."""

import importlib.metadata
import os
import platform
import shutil
import sys
from pathlib import Path

import psutil
import yaml

from factorygraph.io import sha256, verify_artifacts
from factorygraph.phase6.common import read_json, save_new
from factorygraph.phase6.evaluation import graph_integrity
from factorygraph.phase6.integrity import prediction_parity, verify_mapping
from factorygraph.phase7.audit import verify as verify_phase7
from factorygraph.phase7.runtime import ReadOnlyGraph


def output_root():
    path = Path(os.environ.get("FACTORYGRAPH_PHASE8_RUN_DIR", "artifacts/phase8/study"))
    parent = Path("artifacts/phase8").resolve()
    if not path.resolve().is_relative_to(parent) or path.resolve() == parent:
        raise ValueError("Phase 8 output must be a dedicated directory under artifacts/phase8")
    return path


ROOT = output_root()
SHARED = {"README.md", "docs/ARCHITECTURE.md", "docs/ROADMAP.md", "docs/DECISIONS.md"}


def config():
    return yaml.safe_load(Path("configs/phase8/study.yaml").read_text())


def resources():
    return {
        "available_ram_bytes": psutil.virtual_memory().available,
        "total_ram_bytes": psutil.virtual_memory().total,
        "free_disk_bytes": shutil.disk_usage(".").free,
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }


def budget(process=None):
    c, r = config(), resources()
    if r["available_ram_bytes"] < c["minimum_available_ram_bytes"]:
        raise MemoryError("Registered available RAM floor")
    if r["free_disk_bytes"] < c["minimum_free_disk_bytes"]:
        raise OSError("Registered disk floor")
    if process and process.memory_info().rss > c["maximum_service_rss_bytes"]:
        raise MemoryError("Registered service RSS cap")
    return r


def inputs():
    p7 = read_json("docs/results/phase7.json")
    for p, expected in p7["implementation_sha256"].items():
        if sha256(Path(p)) != expected:
            original = Path("artifacts/phase8/study/baseline_shared") / p
            if (
                p in SHARED
                and original.is_file()
                and sha256(original) == expected
                and Path(p).read_bytes().startswith(original.read_bytes())
            ):
                continue  # Only documented chronological additions to shared documents.
            raise ValueError("Accepted Phase 7 implementation drift")
    verify_artifacts(Path("artifacts/phase7"))
    old = verify_phase7()
    paths = set(read_json("artifacts/phase7/protected.json"))
    paths.update(p7["implementation_sha256"])
    paths.add("docs/results/phase7.json")
    paths.add("artifacts/phase7/artifact_manifest.json")
    paths.update(
        (Path("artifacts/phase7") / p).as_posix()
        for p in read_json("artifacts/phase7/artifact_manifest.json")
    )
    return old, {p: sha256(Path(p)) for p in sorted(paths - SHARED)}


def register():
    if ROOT.exists():
        raise ValueError("Choose a fresh Phase 8 study; never overwrite registration")
    budget()
    old, protected = inputs()
    graph = graph_integrity()
    parity = prediction_parity()
    db = ReadOnlyGraph()
    try:
        with db.driver.session(database="neo4j", default_access_mode="READ") as session:
            version = session.execute_read(
                lambda tx: tx.run(
                    "CALL dbms.components() YIELD name,versions,edition "
                    "RETURN name,versions,edition"
                ).data()
            )
            indexes = session.execute_read(
                lambda tx: tx.run(
                    "SHOW INDEXES YIELD name,type,state,labelsOrTypes,properties "
                    "RETURN name,type,state,labelsOrTypes,properties ORDER BY name"
                ).data()
            )
    finally:
        db.close()
    processes = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "cpu_times"]):
        command = p.info["cmdline"] or []
        if any("factorygraph.phase7.server" == s or "streamlit" == s for s in command) or (
            p.info["name"] and p.info["name"].lower() == "java.exe"
        ):
            processes.append(
                {
                    "pid": p.pid,
                    "name": p.info["name"],
                    "rss_bytes": p.memory_info().rss,
                    "cpu_seconds": sum(p.cpu_times()[:2]),
                }
            )
    examples = []
    for name in ["new_alert", "cooldown", "non_alert", "missing_forecast"]:
        report = read_json(f"docs/examples/phase6/{name}.json")
        examples.append({"name": name, **report["request"]})
    cases = read_json("artifacts/phase6/study/registration.json")["cases"]
    boundary = next(r for r in cases if r["category"].startswith("boundary_"))
    packages = {
        d.metadata["Name"]: d.version
        for d in importlib.metadata.distributions()
        if d.metadata["Name"]
    }
    code = {
        p.as_posix(): sha256(p)
        for root in [
            "src/factorygraph/phase6",
            "src/factorygraph/phase7",
            "apps/factorygraph_dashboard",
            "requirements",
        ]
        for p in Path(root).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    record = {
        "date": "2026-11-15",
        "status": "registered_before_profiling",
        "config": config(),
        "prior_protected_files": old,
        "protected_files": len(protected),
        "graph": graph,
        "neo4j": version,
        "existing_indexes": indexes,
        "prediction_parity": parity,
        "hardware": {
            "python": sys.version,
            "os": platform.platform(),
            "processor": platform.processor(),
            "physical_cpus": psutil.cpu_count(False),
            "logical_cpus": psutil.cpu_count(),
            **resources(),
        },
        "existing_processes": processes,
        "packages": packages,
        "source_dependency_sha256": code,
        "protocol_sha256": sha256(Path("docs/PHASE8_PROFILING_PROTOCOL.md")),
        "config_sha256": sha256(Path("configs/phase8/study.yaml")),
        "references": examples,
        "boundary": boundary,
        "all_cases": cases,
        "docker": shutil.which("docker"),
        "gpu_work": False,
        "approved_artifact_sha256": {
            p: sha256(Path(p))
            for p in read_json("artifacts/phase6/study/registration.json")["inputs_sha256"]
            if p.startswith("artifacts/baseline/")
        },
    }
    save_new(ROOT / "protected.json", protected)
    save_new(ROOT / "registration.json", record)
    return {"status": record["status"], "protected": len(protected), "graph": graph}


def verify():
    verify_mapping(Path("."), read_json(ROOT / "protected.json"))
    for name in SHARED:
        original = Path("artifacts/phase8/study/baseline_shared") / name
        if original.exists() and not Path(name).read_bytes().startswith(original.read_bytes()):
            raise ValueError("Prior shared-document text changed")
    record = read_json(ROOT / "registration.json")
    if sha256(Path("docs/PHASE8_PROFILING_PROTOCOL.md")) != record["protocol_sha256"]:
        raise ValueError("Registered protocol drift")
    if sha256(Path("configs/phase8/study.yaml")) != record["config_sha256"]:
        raise ValueError("Registered configuration drift")
    return {"protected_files": len(read_json(ROOT / "protected.json")), "graph": graph_integrity()}


if __name__ == "__main__":
    print(register() if len(sys.argv) == 1 or sys.argv[1] == "register" else verify())
