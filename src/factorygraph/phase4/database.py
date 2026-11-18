"""Official driver, scoped schema, parameterized transactions and deterministic import."""

import hashlib
import json
import time
from datetime import UTC, datetime

from factorygraph.phase4.config import SCHEMA_VERSION, GraphConfig, connection
from factorygraph.phase4.source import EVENTS, event_facts, read_sources

LABELS = [
    "GraphBuild",
    "Machine",
    "MachineModel",
    "ComponentType",
    "SensorType",
    "ErrorType",
    "RecordedEvent",
    "DataArtifact",
    "FeatureArtifact",
    "ForecastRun",
]


class GraphDB:
    def __init__(self, config: GraphConfig):
        from neo4j import GraphDatabase

        self.config = config
        uri, user, password = connection()
        self.driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=5, max_transaction_retry_time=10
        )
        try:
            self.driver.verify_connectivity()
        except Exception:
            self.driver.close()
            raise

    def close(self):
        self.driver.close()

    def read(self, query: str, **parameters) -> list[dict]:
        with self.driver.session(database="neo4j", default_access_mode="READ") as session:
            return session.execute_read(
                lambda tx: [
                    record.data()
                    for record in tx.run(query, namespace=self.config.namespace, **parameters)
                ]
            )

    def write(self, query: str, **parameters) -> list[dict]:
        with self.driver.session(database="neo4j") as session:
            return session.execute_write(
                lambda tx: [
                    record.data()
                    for record in tx.run(query, namespace=self.config.namespace, **parameters)
                ]
            )

    def schema(self):
        for label in LABELS:  # Only fixed internal allowlisted labels; never external input.
            self.write(
                f"CREATE CONSTRAINT fg4_{label.lower()} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE (n.namespace,n.id) IS UNIQUE"
            )
        self.write(
            "CREATE INDEX fg4_event_time IF NOT EXISTS FOR (e:RecordedEvent) "
            "ON (e.namespace,e.event_ms)"
        )
        self.write(
            "CREATE INDEX fg4_event_machine_time IF NOT EXISTS FOR (e:RecordedEvent) "
            "ON (e.namespace,e.machine_id,e.event_ms)"
        )
        self.read("CALL db.awaitIndexes(60)")

    def signature(self) -> str:
        nodes = self.read(
            "MATCH (n {namespace:$namespace}) RETURN labels(n) AS labels, "
            "properties(n) AS properties ORDER BY n.id"
        )
        for node in nodes:
            node["labels"].sort()
            node["properties"].pop("ingested_at", None)
        edges = self.read(
            "MATCH (a {namespace:$namespace})-[r]->(b {namespace:$namespace}) "
            "RETURN a.id AS a,type(r) AS type,b.id AS b ORDER BY a,type,b"
        )
        return hashlib.sha256(json.dumps([nodes, edges], sort_keys=True).encode()).hexdigest()

    def counts(self) -> dict:
        return {
            "nodes": self.read(
                "MATCH (n {namespace:$namespace}) UNWIND labels(n) AS label "
                "RETURN label,count(*) AS count ORDER BY label"
            ),
            "relationships": self.read(
                "MATCH (a {namespace:$namespace})-[r]->"
                "(b {namespace:$namespace}) RETURN type(r) AS type,"
                "count(*) AS count ORDER BY type"
            ),
            "total_nodes": self.read("MATCH (n {namespace:$namespace}) RETURN count(n) AS n")[0][
                "n"
            ],
        }


def import_graph(db: GraphDB, config: GraphConfig) -> dict:
    tables, hashes = read_sources(config)
    facts = event_facts(tables, hashes, config.machine_ids)
    build_hash = hashlib.sha256(
        json.dumps([config.digest(), hashes], sort_keys=True).encode()
    ).hexdigest()
    previous = db.read(
        "MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) RETURN b.build_hash AS hash"
    )
    if previous and previous[0]["hash"] != build_hash:
        raise ValueError(
            "Namespace belongs to a different registered build; choose a fresh namespace"
        )
    if not previous and db.read("MATCH (n {namespace:$namespace}) RETURN count(n) AS n")[0]["n"]:
        raise ValueError("Refuse to overwrite existing unowned graph namespace")
    started = time.perf_counter()
    db.schema()
    imported_at = datetime.now(UTC).isoformat()
    db.write(
        "MERGE (b:GraphBuild {namespace:$namespace,id:'build'}) "
        "ON CREATE SET b.build_hash=$hash,b.schema_version=$version,b.ingested_at=$now "
        "SET b.status='loading'",
        hash=build_hash,
        version=SCHEMA_VERSION,
        now=imported_at,
    )
    machines = tables["machines"].loc[tables["machines"].machineID.isin(config.machine_ids)]
    rows = [
        {
            "id": str(r.machineID),
            "machine_id": int(r.machineID),
            "age": float(r.age),
            "model": r.model,
            "source_table": "PdM_machines.csv",
            "source_sha256": hashes["machines"],
            "source_row": int(i) + 1,
        }
        for i, r in machines.iterrows()
    ]
    db.write(
        "UNWIND $rows AS row MERGE (m:Machine {namespace:$namespace,id:row.id}) "
        "SET m += row MERGE (v:MachineModel {namespace:$namespace,id:row.model}) "
        "MERGE (m)-[:HAS_MODEL]->(v)",
        rows=rows,
    )
    for label, codes in [
        ("ComponentType", [f"comp{i}" for i in range(1, 5)]),
        ("ErrorType", [f"error{i}" for i in range(1, 6)]),
        ("SensorType", ["volt", "rotate", "pressure", "vibration"]),
    ]:
        db.write(
            f"UNWIND $codes AS code MERGE (n:{label} {{namespace:$namespace,id:code}})", codes=codes
        )
    db.write(
        "MATCH (m:Machine {namespace:$namespace}),(s:SensorType {namespace:$namespace}) "
        "MERGE (m)-[:HAS_RECORDED_SENSOR_CHANNEL]->(s)"
    )
    from pathlib import Path

    from factorygraph.io import sha256

    artifacts = [
        {
            "id": name,
            "path": str(config.raw_dir / f"PdM_{name}.csv"),
            "sha256": digest,
            "source_table": f"PdM_{name}.csv",
        }
        for name, digest in hashes.items()
    ]
    telemetry = config.processed_dir / "telemetry.parquet"
    artifacts.append(
        {
            "id": "telemetry-parquet",
            "path": str(telemetry),
            "sha256": sha256(telemetry),
            "source_table": "PdM_telemetry.csv",
        }
    )
    db.write(
        "UNWIND $rows AS row MERGE (a:DataArtifact {namespace:$namespace,id:row.id}) SET a += row",
        rows=artifacts,
    )
    db.write(
        "MATCH (m:Machine {namespace:$namespace}),"
        "(a:DataArtifact {namespace:$namespace,id:'telemetry-parquet'}) "
        "MERGE (m)-[:HAS_TELEMETRY_REFERENCE]->(a)"
    )
    db.write(
        "MATCH (p:DataArtifact {namespace:$namespace,id:'telemetry-parquet'}),"
        "(s:DataArtifact {namespace:$namespace,id:'telemetry'}) MERGE (p)-[:DERIVED_FROM]->(s)"
    )
    for table, (label, _field, type_label, relation, type_relation) in EVENTS.items():
        selected = [r for r in facts if r["kind"] == table]
        query = (
            "UNWIND $rows AS row "
            "MATCH (m:Machine {namespace:$namespace,id:toString(row.machine_id)}) "
            f"MATCH (t:{type_label} {{namespace:$namespace,id:row.code}}) "
            "MATCH (a:DataArtifact {namespace:$namespace,id:$table}) "
            f"MERGE (e:RecordedEvent:{label} {{namespace:$namespace,id:row.id}}) "
            "ON CREATE SET e.ingested_at=$now SET e += row "
            f"MERGE (m)-[:{relation}]->(e) MERGE (e)-[:{type_relation}]->(t) "
            "MERGE (e)-[:SOURCED_FROM]->(a) RETURN count(e) AS n"
        )
        for offset in range(0, len(selected), config.batch_size):
            batch = selected[offset : offset + config.batch_size]
            returned = db.write(query, rows=batch, table=table, now=imported_at)
            if returned[0]["n"] != len(batch):
                raise ValueError("Missing relationship endpoints; incomplete import")
    # A derived exact-key match, explicitly not a causal/physical identity assertion.
    db.write(
        "MATCH (f:FailureEvent {namespace:$namespace}),(m:MaintenanceEvent {namespace:$namespace}) "
        "WHERE f.machine_id=m.machine_id AND f.event_ms=m.event_ms AND f.code=m.code "
        "MERGE (f)-[:MATCHES_RECORDED_KEY]->(m)"
    )
    feature = Path("artifacts/phase3/azure/features_test.parquet")
    forecast = Path("artifacts/phase3/azure/forecast_results.json")
    if feature.exists() and forecast.exists():
        db.write(
            "MERGE (f:FeatureArtifact {namespace:$namespace,id:'phase3-test-features'}) "
            "SET f.path=$feature,f.sha256=$feature_hash,f.historical_visibility=false "
            "MERGE (r:ForecastRun {namespace:$namespace,id:'phase3-azure'}) "
            "SET r.path=$forecast,r.sha256=$forecast_hash,r.historical_visibility=false "
            "MERGE (f)-[:DERIVED_FROM]->(r)",
            feature=str(feature),
            feature_hash=sha256(feature),
            forecast=str(forecast),
            forecast_hash=sha256(forecast),
        )
    actual = db.read("MATCH (e:RecordedEvent {namespace:$namespace}) RETURN properties(e) AS e")
    by_id = {r["e"]["id"]: r["e"] for r in actual}
    if len(by_id) != len(facts) or any(
        any(by_id.get(r["id"], {}).get(k) != v for k, v in r.items()) for r in facts
    ):
        raise ValueError("Source-row/node reconciliation failed")
    db.write("MATCH (b:GraphBuild {namespace:$namespace,id:'build'}) SET b.status='complete'")
    return {
        "status": "completed",
        "seconds": time.perf_counter() - started,
        "event_rows": len(facts),
        "events_per_second": len(facts) / (time.perf_counter() - started),
        "build_hash": build_hash,
        "source_sha256": hashes,
        "counts": db.counts(),
        "signature": db.signature(),
        "source_rows_reconciled": True,
    }
