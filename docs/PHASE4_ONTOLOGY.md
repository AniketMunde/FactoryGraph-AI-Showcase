# Phase 4 ontology v1 — 2026-11-12

Schema identifier: `factorygraph-phase4-v1`. This property graph represents recorded facts
from the pinned Microsoft synthetic benchmark, not a physical digital twin. Source mappings
were checked against actual CSVs and the [pinned Microsoft notebook](https://github.com/microsoft/sqlworkshops/blob/e836f4e866028db7fd7d1a66b88f79664a1f4eac/SQLServerAndAzureMachineLearning/ML%20Services%20for%20SQL%20Server/notebooks/Predictive%20Maintenance%20in%20Python%20Notebook.ipynb).
Errors are recorded non-breaking messages, not failures. Maintenance records reference
component categories; neither files nor documentation identify physical part instances.

## Labels, identities and properties

Every node has `namespace` (isolated build membership) and string `id`. Composite uniqueness
constraints apply per label. Each typed event also has the shared `RecordedEvent` label.

| Label | Identity inside namespace | Properties/source mapping |
|---|---|---|
| GraphBuild | `build` | build/config hash, schema version, status, measured first import time |
| Machine | decimal machineID | machine_id, age from machines CSV; source table/row/file hash; age is recorded static metadata, not continuously updated age |
| MachineModel | model1…model4 present in membership | recorded categorical model code; no manufacturer inferred |
| ComponentType | comp1…comp4 | categorical dictionary from source vocabulary, not installed parts |
| SensorType | volt, rotate, pressure, vibration | observed telemetry column names; no sensor serial number or physical placement |
| ErrorType | error1…error5 | recorded error-code vocabulary; no assumed fault mechanism |
| ErrorEvent | source-backed SHA-256 identity | one errors CSV record, errorID mapped to code |
| MaintenanceEvent | source-backed SHA-256 identity | one maintenance CSV record, comp mapped to code |
| FailureEvent | source-backed SHA-256 identity | one failures CSV record, failure mapped to code |
| DataArtifact | table name or telemetry-parquet | relative file path, SHA-256, source table; five raw sources and existing dense telemetry Parquet |
| ForecastRun | phase3-azure | verified Phase 3 forecast-results path/hash; historical_visibility=false |
| FeatureArtifact | phase3-test-features | verified Phase 3 exported-features path/hash; historical_visibility=false |

Event identity hashes `(source revision, full source-file SHA-256, source record ID)`.
Source record ID is `PdM_<table>.csv:data-row:<1-based ordinal excluding header>`.
Reordering/changing an input changes its hash and requires a new namespace/build. Two
different records at one timestamp remain distinct. Exact duplicate source keys fail
validation rather than being silently collapsed. The actual data have 577 error, 1,514
maintenance and 84 failure rows participating in repeated machine/timestamp groups;
their differing type/category records are legitimate separate source facts.

Each event has `machine_id`, `kind`, `code`, integer UTC epoch `event_ms`, ISO UTC
`event_timestamp`, `source_dataset` with pinned revision, `source_table`, `source_row`,
`source_sha256`, `source_record_id`, normalized `source_payload_sha256`, measured first
graph `ingested_at`, and explicit `visibility_policy`. There is **no measured source
recorded_at/available_at**. Graph ingestion time in 2026 must not masquerade as source
availability in 2015. Event-time immediate availability is an assumption, stated separately.

## Relationships and cardinalities

All endpoints must have identical namespace. Arrows below are directed.

| Relationship | Endpoints | Cardinality and meaning |
|---|---|---|
| HAS_MODEL | Machine → MachineModel | exactly one model per machine; model has one or more member machines |
| HAS_RECORDED_SENSOR_CHANNEL | Machine → SensorType | four per audited machine; observed channel schema only |
| RECORDED_ERROR | Machine → ErrorEvent | zero or more per machine; exactly one machine per event |
| HAS_MAINTENANCE_EVENT | Machine → MaintenanceEvent | zero or more; exactly one machine per event |
| HAS_FAILURE_EVENT | Machine → FailureEvent | zero or more; exactly one machine per event |
| HAS_ERROR_TYPE | ErrorEvent → ErrorType | exactly one type per error record |
| REFERENCES_COMPONENT_TYPE | MaintenanceEvent/FailureEvent → ComponentType | exactly one category per record |
| SOURCED_FROM | RecordedEvent → DataArtifact | exactly one immutable raw table reference |
| HAS_TELEMETRY_REFERENCE | Machine → DataArtifact | one pointer to the existing dense telemetry Parquet, no numerical observations copied into graph |
| DERIVED_FROM | telemetry DataArtifact → raw telemetry DataArtifact | verified artifact lineage |
| DERIVED_FROM | Phase 3 FeatureArtifact → ForecastRun | research artifact lineage, not historical physical evidence |
| MATCHES_RECORDED_KEY | FailureEvent → MaintenanceEvent | derived exact equality of machine/time/component code; not physical identity, repair causation or root cause |

All source-mapping edges represent recorded associations. MATCHES_RECORDED_KEY is an
explicitly derived equality relation. DERIVED_FROM is verified file lineage. Counts and
rates are derived analytics, never new observed events. Exactly 743 of 761 failure rows
match a maintenance row on this key; 18 do not. The graph retains both source tables.
Maintenance and failure feature families count records separately; their sum is never
described as a count of unique physical breakdowns or repairs.

## Time and visibility

Source timestamps lack a zone; normalize to UTC by explicit assumption, consistently
with prior phases. Static machine/model metadata and fixed category dictionaries are
assumed known at study start, with no fictitious installation/availability timestamps.
Source-backed historical events use **event_ms < cutoff_ms**. A historical rolling
window is `[T−window,T)`. Same-model peers are other registered machines with the same
recorded model, excluding the subject; they are not physically connected machines.
Every peer event uses the same strict cutoff and window. Full topology/degree and
unfiltered neighbor counts must never become historical features.

The safe query layer traverses only visible event edges, then their recorded types.
Research artifacts, GraphBuild metadata, complete-file bounds and catalog information
are deliberately excluded from historical neighborhoods/prediction features. An artifact
produced in 2026 is not a 2015 observation. Source hashing and provenance remain usable
for auditing without asserting historical artifact availability.

Dense telemetry stays in accepted Parquet. SensorType and DataArtifact identify its schema
and location; they do not claim graph-native sensor-value storage. A future version could
add source-supported summaries with explicit windows and availability, under a new schema.

## Parameterized Cypher examples

Parameters include namespace, machine, cutoff/start UTC epoch milliseconds and bounded
pagination. Names/labels/relationship types are fixed internal constants, never user text.

```cypher
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})
      -[:RECORDED_ERROR|HAS_MAINTENANCE_EVENT|HAS_FAILURE_EVENT]->(e:RecordedEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff AND e.event_ms>=$start
RETURN e.source_table,e.source_record_id,e.event_timestamp,e.code
ORDER BY e.event_ms,e.kind,e.id SKIP $offset LIMIT $limit
```

```cypher
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})
      -[:HAS_MAINTENANCE_EVENT]->(e:MaintenanceEvent)
      -[:REFERENCES_COMPONENT_TYPE]->(c:ComponentType {namespace:$namespace,id:$component})
WHERE e.event_ms<$cutoff
RETURN e.source_record_id,e.event_timestamp,c.id ORDER BY e.event_ms,e.id
```

```cypher
MATCH (m:Machine {namespace:$namespace,id:toString($machine)})-[:HAS_MODEL]->(v:MachineModel)
      <-[:HAS_MODEL]-(peer:Machine {namespace:$namespace})
WHERE peer.id<>m.id
OPTIONAL MATCH (peer)-[:HAS_FAILURE_EVENT]->(e:FailureEvent)
WHERE e.namespace=$namespace AND e.event_ms<$cutoff AND e.event_ms>=$start
RETURN v.id,count(DISTINCT peer) AS peers,count(e) AS failure_records
```

## Unsupported assertions

No physical Component instances, installation dates, bill of materials, suppliers,
factory/line/location entities, real inter-machine dependencies, error→failure causes,
sensor-anomaly root causes or diagnosis edges are supported. Sharing a model is a
metadata association. Co-occurrence/equal keys cannot prove causation. Graph aggregates
can also be computed relationally; representation/query/provenance value is separate
from any predictive benefit, which is untested until Phase 5.
