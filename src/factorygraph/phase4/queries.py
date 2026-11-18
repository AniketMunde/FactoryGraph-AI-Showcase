"""Bounded, deterministic, parameterized historical queries; no unfiltered graph degree."""

from datetime import datetime

from pydantic import BaseModel, Field

from factorygraph.phase4.config import milliseconds, timestamp
from factorygraph.phase4.database import GraphDB

HISTORY = """
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})
      -[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e:RecordedEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff AND e.event_ms>=$start
      AND e.kind IN $kinds AND ($component IS NULL OR e.code=$component)
RETURN properties(e) AS fact
ORDER BY e.event_ms,e.kind,e.id SKIP $offset LIMIT $limit
"""
COUNTS = """
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})
      -[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e:RecordedEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff AND e.event_ms>=$start
RETURN e.kind AS kind,e.code AS code,count(e) AS count ORDER BY kind,code
"""
PEERS = """
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})-[:HAS_MODEL]->(v:MachineModel)
      <-[:HAS_MODEL]-(p:Machine {namespace:$namespace})
WHERE p.id<>m.id
RETURN p.machine_id AS machine_id,v.id AS model ORDER BY machine_id
"""
PEER_COUNTS = """
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})-[:HAS_MODEL]->(v:MachineModel)
      <-[:HAS_MODEL]-(p:Machine {namespace:$namespace})
WHERE p.id<>m.id
OPTIONAL MATCH (p)-[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e:RecordedEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff AND e.event_ms>=$start
RETURN v.id AS model,count(DISTINCT p) AS eligible_peer_machines,
       count(CASE WHEN e.kind='failures' THEN 1 END) AS failure_records,
       count(CASE WHEN e.kind='maint' THEN 1 END) AS maintenance_records,
       count(CASE WHEN e.kind='errors' THEN 1 END) AS error_records
"""
FLEET_FACTS = """
MATCH (m:Machine {namespace:$namespace})
      -[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e:RecordedEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff
RETURN properties(e) AS fact ORDER BY e.event_ms,e.kind,e.id SKIP $offset LIMIT $limit
"""


def machine_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("Positive integer machine ID required")
    return value


class EvidenceRequest(BaseModel):
    machine_id: int = Field(gt=0, strict=True)
    cutoff: datetime
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class HistoricalQueries:
    def __init__(self, database: GraphDB):
        self.db = database

    def history(
        self,
        machine: int,
        cutoff,
        *,
        start=None,
        kinds=None,
        component=None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict]:
        if not 1 <= limit <= 10000 or offset < 0:
            raise ValueError("Bounded pagination required")
        if component is not None and component not in [f"comp{i}" for i in range(1, 5)]:
            raise ValueError("Unknown component category")
        kinds = kinds or ["errors", "maint", "failures"]
        if not set(kinds).issubset({"errors", "maint", "failures"}):
            raise ValueError("Unknown event source")
        return [
            r["fact"]
            for r in self.db.read(
                HISTORY,
                machine=machine_id(machine),
                cutoff=milliseconds(cutoff),
                start=milliseconds(start) if start is not None else -9223372036854775808,
                kinds=kinds,
                component=component,
                limit=limit,
                offset=offset,
            )
        ]

    def counts(self, machine: int, cutoff, start) -> list[dict]:
        return self.db.read(
            COUNTS,
            machine=machine_id(machine),
            cutoff=milliseconds(cutoff),
            start=milliseconds(start),
        )

    def peers(self, machine: int) -> list[dict]:
        return self.db.read(PEERS, machine=machine_id(machine))

    def peer_counts(self, machine: int, cutoff, start) -> list[dict]:
        return self.db.read(
            PEER_COUNTS,
            machine=machine_id(machine),
            cutoff=milliseconds(cutoff),
            start=milliseconds(start),
        )

    def neighborhood(self, request: EvidenceRequest) -> dict:
        cutoff = timestamp(request.cutoff)
        machines = self.db.read(
            "MATCH (m:Machine {namespace:$namespace,id:toString($machine)})"
            "-[:HAS_MODEL]->(v:MachineModel) "
            "RETURN properties(m) AS machine,v.id AS model",
            machine=request.machine_id,
        )
        if not machines:
            raise ValueError("Unknown machine")
        facts = self.history(request.machine_id, cutoff, limit=request.limit, offset=request.offset)
        return {
            "request": request.model_dump(mode="json"),
            "cutoff_exclusive": cutoff.isoformat(),
            "machine": machines[0],
            "observed_source_records": facts,
            "visible_types": sorted({(r["kind"], r["code"]) for r in facts}),
            "interpretation": "Recorded history, not diagnosis or causal explanation",
            "visibility_assumption": (
                "Source has no measured availability timestamps; event-time assumed"
            ),
            "catalog_artifacts_in_historical_context": False,
            "pagination": {
                "offset": request.offset,
                "limit": request.limit,
                "returned": len(facts),
            },
        }

    def fleet_facts(self, cutoff) -> list[dict]:
        result = []
        offset = 0
        while True:
            rows = self.db.read(FLEET_FACTS, cutoff=milliseconds(cutoff), offset=offset, limit=1000)
            result.extend(r["fact"] for r in rows)
            if len(rows) < 1000:
                return result
            offset += len(rows)
