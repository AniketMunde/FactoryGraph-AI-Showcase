"""Offline graph snapshot export and fresh Compose-only initialization."""

import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from neo4j import GraphDatabase

from factorygraph.io import sha256
from factorygraph.phase4.config import load_config
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.maintenance import EDGE_TYPES, NODE_LABELS, backup
from factorygraph.phase6.common import read_json, save_new


def export():
    db = GraphDB(load_config(Path("configs/phase4/full.yaml")))
    try:
        expected = read_json("artifacts/phase4/full/build.json")
        if db.signature() != expected["signature"] or db.counts() != expected["counts"]:
            raise ValueError("Original graph reconciliation failed")
        result = backup(db, Path("artifacts/phase7/graph.json"))
        save_new(Path("artifacts/phase7/graph_manifest.json"), result)
        return {
            "nodes": result["nodes"],
            "edges": result["edges"],
            "read_only_original_export": True,
        }
    finally:
        db.close()


def initialize():
    uri = os.environ.get("FACTORYGRAPH_NEO4J_URI", "")
    if urlparse(uri).hostname != "neo4j" or os.environ.get("FG7_CONTAINER") != "1":
        raise ValueError("Bootstrap is restricted to the isolated Compose hostname")
    expected = read_json("/bootstrap/graph_manifest.json")
    path = Path("/bootstrap/graph.json")
    if sha256(path) != expected["sha256"]:
        raise ValueError("Graph snapshot integrity failed")
    snapshot = read_json(path)
    db = GraphDB.__new__(GraphDB)
    db.config = load_config(Path("configs/phase4/full.yaml"))
    password = Path(os.environ["FG7_NEO4J_PASSWORD_FILE"]).read_text().strip()
    db.driver = GraphDatabase.driver(uri, auth=("neo4j", password))
    try:
        if db.counts()["total_nodes"]:
            if db.signature() == snapshot["logical_signature"]:
                return {"status": "existing_identical_isolated_graph"}
            raise ValueError("Nonempty graph differs; refuse overwrite")
        nodes, edges = defaultdict(list), defaultdict(list)
        for item in snapshot["nodes"]:
            if (
                not set(item["labels"]) <= NODE_LABELS
                or item["properties"]["namespace"] != db.config.namespace
            ):
                raise ValueError("Unapproved snapshot schema/namespace")
            nodes[tuple(sorted(item["labels"]))].append(item["properties"])
        for edge in snapshot["edges"]:
            if edge["type"] not in EDGE_TYPES:
                raise ValueError("Unapproved relationship type")
            edges[edge["type"]].append(edge)
        db.schema()
        for labels, rows in nodes.items():
            label = ":".join(labels)
            for offset in range(0, len(rows), 500):
                db.write(
                    f"UNWIND $rows AS row CREATE (n:{label}) SET n=row",
                    rows=rows[offset : offset + 500],
                )
        for relation, rows in edges.items():
            for offset in range(0, len(rows), 500):
                result = db.write(
                    "UNWIND $rows AS row MATCH (a {namespace:$namespace,id:row.a}),"
                    "(b {namespace:$namespace,id:row.b}) "
                    f"CREATE (a)-[:{relation}]->(b) RETURN count(*) AS n",
                    rows=rows[offset : offset + 500],
                )
                if result[0]["n"] != len(rows[offset : offset + 500]):
                    raise ValueError("Missing graph endpoints")
        if db.signature() != snapshot["logical_signature"]:
            raise ValueError("Reconstructed graph signature differs; stop")
        return {"status": "isolated_graph_reconciled", "counts": db.counts()}
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["export", "initialize"])
    print(globals()[parser.parse_args().stage]())
