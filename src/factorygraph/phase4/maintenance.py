"""Explicitly scoped logical backup/reset; never delete another graph or database."""

import argparse
import json
from pathlib import Path

from factorygraph.io import sha256, write_json
from factorygraph.phase4.config import load_config
from factorygraph.phase4.database import LABELS, GraphDB

EDGE_TYPES = {
    "HAS_MODEL",
    "HAS_RECORDED_SENSOR_CHANNEL",
    "RECORDED_ERROR",
    "HAS_MAINTENANCE_EVENT",
    "HAS_FAILURE_EVENT",
    "HAS_ERROR_TYPE",
    "REFERENCES_COMPONENT_TYPE",
    "SOURCED_FROM",
    "HAS_TELEMETRY_REFERENCE",
    "DERIVED_FROM",
    "MATCHES_RECORDED_KEY",
}
NODE_LABELS = set(LABELS) | {"ErrorEvent", "MaintenanceEvent", "FailureEvent"}


def backup(db: GraphDB, target: Path) -> dict:
    if target.exists():
        raise ValueError("Backup exists; refusing overwrite")
    before = db.signature()
    nodes = db.read(
        "MATCH (n {namespace:$namespace}) RETURN labels(n) AS labels,"
        "properties(n) AS properties ORDER BY n.id"
    )
    edges = db.read(
        "MATCH (a {namespace:$namespace})-[r]->(b {namespace:$namespace}) "
        "RETURN a.id AS a,type(r) AS type,b.id AS b ORDER BY a,type,b"
    )
    if before != db.signature():
        raise ValueError("Graph changed during backup; retry after writes stop")
    record = {
        "namespace": db.config.namespace,
        "logical_signature": before,
        "nodes": nodes,
        "edges": edges,
    }
    write_json(target, record)
    return {"path": str(target), "sha256": sha256(target), "nodes": len(nodes), "edges": len(edges)}


def restore(db: GraphDB, path: Path, expected_sha256: str):
    if sha256(path) != expected_sha256:
        raise ValueError("Backup checksum failed")
    if db.read("MATCH (n {namespace:$namespace}) RETURN count(n) AS n")[0]["n"]:
        raise ValueError("Restore requires an empty fresh namespace")
    record = json.loads(path.read_text())
    for node in record["nodes"]:
        if not set(node["labels"]).issubset(NODE_LABELS):
            raise ValueError("Unknown backup node label")
    if any(e["type"] not in EDGE_TYPES for e in record["edges"]):
        raise ValueError("Unknown backup relationship type")
    db.schema()
    for node in record["nodes"]:
        props = {**node["properties"], "namespace": db.config.namespace}
        labels = ":".join(sorted(node["labels"]))  # Validated against fixed allowlist.
        db.write(f"CREATE (n:{labels}) SET n=$properties", properties=props)
    for edge in record["edges"]:
        result = db.write(
            "MATCH (a {namespace:$namespace,id:$a}),(b {namespace:$namespace,id:$b}) "
            f"CREATE (a)-[:{edge['type']}]->(b) RETURN count(*) AS n",
            a=edge["a"],
            b=edge["b"],
        )
        if result[0]["n"] != 1:
            raise ValueError("Backup endpoint missing")
    # A forensic copy carries original provenance; it cannot silently resume a new import.
    db.write(
        "MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) "
        "SET b.status='restored_read_only',b.restored_from_namespace=$original",
        original=record["namespace"],
    )
    return {"status": "restored_forensic_copy", "counts": db.counts()}


def reset(db: GraphDB, expected_build_hash: str):
    marker = db.read(
        "MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) RETURN b.build_hash AS hash"
    )
    if not marker or marker[0]["hash"] != expected_build_hash:
        raise ValueError("Reset requires the exact owned build hash")
    db.write("MATCH (n {namespace:$namespace}) DETACH DELETE n")
    return {"status": "namespace_reset", "namespace": db.config.namespace}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["backup", "restore", "reset"])
    parser.add_argument("--config", type=Path, default=Path("configs/phase4/full.yaml"))
    parser.add_argument("--path", type=Path, default=Path("artifacts/phase4/full-backup.json"))
    parser.add_argument("--expected-hash")
    args = parser.parse_args()
    database = GraphDB(load_config(args.config))
    try:
        if args.stage == "backup":
            result = backup(database, args.path)
        elif args.stage == "restore":
            result = restore(database, args.path, args.expected_hash)
        else:
            result = reset(database, args.expected_hash)
        print(json.dumps(result))
    finally:
        database.close()
