# Phase 4 registered experiment — 2026-11-12

Register before pilot/full graph measurements. Preserve accepted Phases 1–3 and MetroPT
failure evidence. Graph scope is only the verified Azure five-table synthetic dataset.
No model retraining, fusion, graph algorithm plugin, chatbot, dashboard or deployment.

Gate A: verify accepted manifests/source hashes; capture all 963 existing historical
files selected in `artifacts/phase4/protected.json`. Recheck after execution. Gate B:
actual schemas/categories/uniqueness/machine membership and maintenance/failure overlap
are audited; formal ontology v1 is source-supported and names unsupported relationships.
Gate C: genuine local Neo4j Community 5.26.33, official Python driver 6.4.1, pinned
Azul JRE 21.0.13.0.3; confirm versions/authentication/localhost/resource feasibility.
Docker absent on PATH, so use supported Windows ZIP, no machine-wide service installation.

Gate D pilot: machines **[1,17,42,73,100]**, chosen before query quality/timing. Build scoped
namespace fg_phase4_pilot_v1 from all their verified event records plus dictionaries and
artifact references. Import twice; canonical logical signatures/counts must match. No
reduction to favorable source records. Schema/indexes and source endpoint checks must pass.
Gate E: compare graph counts, source identities, historical neighborhoods and model-peer
statistics against independent Pandas calculations of source Parquet tables. Synthetic
fixture integration separately proves exact-cutoff exclusion and future-event invariance.
Only pass pilot if every correctness check passes, free RAM >=3GB/free disk >=2GB, and
pilot-based linear full import projection with 2x margin plus 120s is <=1800s. A slower
graph than Pandas is an acceptable result. No graph speedup is assumed.

Gate F: import all 100 machines/all 7,966 event records in fg_phase4_full_v1 with identical
schema/protocol. Repeat import to verify idempotency. A loading build can resume by rerunning
the same hash/config and idempotent batches; changed input/config needs a fresh namespace.
Do not overwrite another user's database. Logical signatures ignore measured import time,
while preserving it on first creation. Keep full source-row/node reconciliation and typed
edge/cardinality checks. Gate G exports all accepted historical split snapshot keys using
strict event prefixes and a fixed **720h/30-day** window, not selected on labels.

Feature inputs are fetched from the genuine graph with an upper cutoff, then vectorized
prefix searches use strict `<snapshot` per row, including peer aggregates. Do not use a
full-graph degree/projection. Export train/calibration/validation/test separately; require
exact Phase 1 test keys. Counts are recorded-source counts, not unique physical event
counts. All feature families and missingness are frozen in the contract; no subsets chosen
using test labels. Independent direct masks validate sampled keys from every split.
Original 57 Phase 1 and 77 test-only Phase 3 features remain unchanged; no historical
Chronos features or complete fusion-training matrix is assumed to exist.

Registered query workload: machines [1,17,42,73,100] crossed with cutoffs
[2015-02-01,2015-05-01,2015-08-01,2015-10-15,2015-12-31] at 00:00 UTC.
For each pair, execute own historical kind/type counts over 30d and model-peer counts
over 30d, plus bounded historical evidence (limit100). Also fetch full-fleet visible
facts at each cutoff. Run **three repetitions**, deterministic order, record all latency
samples and p50/p95/mean. Compare equivalent counts to in-memory Pandas source Parquet
aggregations. Report source loading separately, no claim of production concurrency or
database-size scalability. Use parameterized Cypher, never interpolate user values.

Record construction/re-import time, event throughput, actual nodes/relationships, source
row reconciliation, graph namespace logical digest, database+transaction disk bytes,
observable process RSS/peak memory, query/as-of costs and export wall time. Neo4j shared
instance footprint includes system DB and pilot/test namespaces, not isolated per-node
storage. Preserve runtime/download/license notices and failures. Gate H: all original70
and new unit/real-database integration tests, Ruff, locks/package checks and preservation.
If any gate cannot pass, preserve partial evidence and report incomplete rather than
substitute Python graphs or weaken temporal correctness. Graph capabilities and additional
model-peer context do not demonstrate predictive improvement.
