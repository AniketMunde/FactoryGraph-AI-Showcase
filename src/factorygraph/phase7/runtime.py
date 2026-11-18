"""New interface boundaries over unchanged Phase 6 behavior; no prediction implementation."""

import copy
import os
import time
from collections import deque
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase, unit_of_work
from pydantic import PrivateAttr

from factorygraph.io import sha256
from factorygraph.phase4.config import load_config as graph_config
from factorygraph.phase4.database import GraphDB
from factorygraph.phase4.queries import COUNTS, FLEET_FACTS, HISTORY, PEER_COUNTS, PEERS
from factorygraph.phase6.common import Config, iso, read_json
from factorygraph.phase6.schema import CaseReport
from factorygraph.phase6.service import CaseReportBuilder

BANNER = (
    "Research demonstration using synthetic historical industrial data."
    " Not validated for operational machinery decisions."
)
MACHINE_QUERY = (
    "MATCH (m:Machine {namespace:$namespace,id:toString($machine)})"
    "-[:HAS_MODEL]->(v:MachineModel) "
    "RETURN properties(m) AS machine,v.id AS model"
)
BUILD_QUERY = (
    "MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) RETURN "
    "b.build_hash AS build_hash,b.schema_version AS schema_version,b.status AS status"
)
AUDIT_QUERIES = {
    (
        "MATCH (n {namespace:$namespace}) RETURN labels(n) AS labels, "
        "properties(n) AS properties ORDER BY n.id"
    ),
    (
        "MATCH (a {namespace:$namespace})-[r]->(b {namespace:$namespace}) "
        "RETURN a.id AS a,type(r) AS type,b.id AS b ORDER BY a,type,b"
    ),
    (
        "MATCH (n {namespace:$namespace}) UNWIND labels(n) AS label RETURN "
        "label,count(*) AS count ORDER BY label"
    ),
    (
        "MATCH (a {namespace:$namespace})-[r]->(b {namespace:$namespace}) "
        "RETURN type(r) AS type,count(*) AS count ORDER BY type"
    ),
    "MATCH (n {namespace:$namespace}) RETURN count(n) AS n",
}


class ReadOnlyGraph(GraphDB):
    """No write method; fixed query allowlist, official driver read transactions."""

    def __init__(self):
        self.config = graph_config(Path("configs/phase4/full.yaml"))
        uri = os.environ.get("FACTORYGRAPH_NEO4J_URI", "bolt://127.0.0.1:17687")
        from urllib.parse import urlparse

        hosts = {"127.0.0.1", "localhost"}
        if os.environ.get("FG7_CONTAINER") == "1":
            hosts.add("neo4j")
        if urlparse(uri).hostname not in hosts or urlparse(uri).scheme != "bolt":
            raise ValueError("Unapproved graph destination")
        password = os.environ.get("FACTORYGRAPH_NEO4J_PASSWORD")
        if os.environ.get("FG7_NEO4J_PASSWORD_FILE"):
            password = Path(os.environ["FG7_NEO4J_PASSWORD_FILE"]).read_text().strip()
        user = os.environ.get("FACTORYGRAPH_NEO4J_USER", "neo4j")
        if not password:
            raise ValueError("Graph credential unavailable")
        self.driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=3, max_transaction_retry_time=2
        )
        self.driver.verify_connectivity()

    def read(self, query, **parameters):
        if query not in AUDIT_QUERIES | {
            HISTORY,
            COUNTS,
            PEERS,
            PEER_COUNTS,
            FLEET_FACTS,
            MACHINE_QUERY,
            BUILD_QUERY,
            "RETURN 1 AS ok",
        }:
            raise ValueError("Unapproved graph query")
        with self.driver.session(database="neo4j", default_access_mode="READ") as session:

            @unit_of_work(timeout=30 if query in AUDIT_QUERIES else 5)
            def run(tx):
                return [
                    r.data() for r in tx.run(query, namespace=self.config.namespace, **parameters)
                ]

            return session.execute_read(run)

    def write(self, *_args, **_kwargs):
        raise PermissionError("Application graph writes are prohibited")


class PortableConfig(Config):
    _registered_spelling: str = PrivateAttr(default="artifacts\\phase6\\study")

    def model_dump(self, *args, **kwargs):
        result = super().model_dump(*args, **kwargs)
        if kwargs.get("mode") == "json":
            result["run_dir"] = self._registered_spelling
        return result


def project(report):
    CaseReport.model_validate(report)
    result = copy.deepcopy(report)
    supplementary = result["temporal_context"].get("supplementary_chronos_context", {})
    supplementary.pop("artifact_path", None)
    CaseReport.model_validate(result)
    return result


def utc(value):
    parsed = pd.Timestamp(value)
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timezone-aware UTC snapshot required")
    return parsed.tz_convert("UTC")


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.builder = None
        self.db = None
        self.metrics = deque(maxlen=256)
        start = time.perf_counter()
        if settings.mode == "gallery":
            root = settings.gallery_directory
            manifest = read_json(root / "manifest.json")
            self.gallery = {}
            for name, record in manifest.items():
                path = root / Path(record["path"]).name
                if sha256(path) != record["sha256"]:
                    raise ValueError("Gallery integrity failed")
                self.gallery[name] = project(read_json(path))
        else:
            record = read_json("artifacts/phase6/study/registration.json")
            values = dict(record["config"])
            values["run_dir"] = Path("artifacts/phase6/study")
            config = PortableConfig.model_validate(values).check()
            config._registered_spelling = record["config"]["run_dir"]
            self.db = ReadOnlyGraph()
            try:
                self.builder = CaseReportBuilder(config, database=self.db)
                for name in self.builder.registry.hashes:
                    self.builder.registry.require(name)
                if any(
                    [
                        self.builder.predictions.error,
                        self.builder.catalog.error,
                        self.builder.evidence.error,
                        self.builder.temporal.error,
                    ]
                ):
                    raise ValueError("Required Phase 6 dependency failed")
                if not self.ready():
                    raise ValueError("Graph identity unavailable")
                expected = read_json("artifacts/phase4/full/build.json")
                if (
                    self.db.signature() != expected["signature"]
                    or self.db.counts() != expected["counts"]
                ):
                    raise ValueError("Graph reconciliation failed")
            except Exception:
                self.db.close()
                raise
        self.startup_seconds = time.perf_counter() - start

    def ready(self):
        if self.settings.mode == "gallery":
            return True
        try:
            expected = self.builder.evidence.identity
            actual = self.db.read(BUILD_QUERY)
            return actual == [
                {
                    "build_hash": expected["build_hash"],
                    "schema_version": expected["schema_version"],
                    "status": "complete",
                }
            ]
        except Exception:
            return False

    def machines(self):
        if self.settings.mode == "gallery":
            return [
                {"machine_id": m, "model": "saved-case membership"}
                for m in sorted({c["request"]["machine_id"] for c in self.gallery.values()})
            ]
        return [
            {"machine_id": int(i), "model": str(row.model)}
            for i, row in self.builder.catalog.machines.sort_index().iterrows()
        ]

    def snapshots(self, machine):
        if self.settings.mode == "gallery":
            return [
                {
                    "snapshot": c["request"]["snapshot"],
                    "eligibility": "saved_case",
                    "gallery_id": name,
                }
                for name, c in self.gallery.items()
                if c["request"]["machine_id"] == machine
            ]
        keys = self.builder.temporal.context.index
        return [
            {
                "snapshot": iso(t),
                "eligibility": "primary"
                if (machine, t) in self.builder.predictions.index.index
                else "evidence_only",
            }
            for m, t in keys
            if m == machine
        ]

    def case(self, machine, snapshot):
        if self.settings.mode == "gallery":
            for c in self.gallery.values():
                if (
                    c["request"]["machine_id"] == machine
                    and utc(c["request"]["snapshot"]) == snapshot
                ):
                    return copy.deepcopy(c)
            raise LookupError("Unsupported saved case")
        return project(self.builder.build(machine, snapshot))

    def telemetry(self, machine, snapshot, hours):
        if self.settings.mode != "full":
            raise LookupError("Telemetry is not a gallery capability")
        frame = self.builder.catalog.tables["telemetry"]
        selected = frame.loc[
            (frame.machineID == machine)
            & (frame.datetime < snapshot)
            & (frame.datetime >= snapshot - pd.Timedelta(hours=hours))
        ]
        return {
            "machine_id": machine,
            "cutoff_exclusive": iso(snapshot),
            "units": "Original source channel units; no residual scores plotted as telemetry",
            "source_sha256": self.builder.catalog.hashes["telemetry"],
            "observations": [
                {
                    "timestamp": iso(r.datetime),
                    **{
                        c: float(getattr(r, c)) for c in ["volt", "rotate", "pressure", "vibration"]
                    },
                }
                for r in selected.itertuples()
            ],
        }

    def fleet(self, snapshot, machines):
        if self.settings.mode != "full":
            raise LookupError("Arbitrary fleet replay is disabled in gallery")
        return [project(c) for c in self.builder.fleet(snapshot, machines)]

    def close(self):
        if self.builder:
            self.builder.close()
        if self.db:
            self.db.close()
