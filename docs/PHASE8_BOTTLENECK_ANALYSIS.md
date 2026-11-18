# Phase 8 measured bottleneck admission — 2026-11-15

The corrected unchanged-baseline profiling pass completed in 19.03s, including service
startup, controls and graceful shutdown. The initial attempt is retained: the harness
incorrectly expected 200 for an off-grid Phase 6 event timestamp; the unchanged API
correctly returned 404. A preregistered correction retained that 404 control and added
the existing supported March 6 09:00 evidence-only report. No candidate existed then.

The profiled 100-machine HTTP response took 9.813s in outer ASGI scope. Nested stages:

| Section | Seconds / calls | Meaning |
|---|---:|---|
| Complete builder fleet | 5.040 / 1 | All 100 reports, includes graph/source/context/rules |
| Managed read/query retrieval | 3.888 / 701 | Seven read transactions per case plus readiness |
| Exact snapshot enumeration | 3.838 / 100 | Repeated full 282,522-key iteration and timestamp formatting |
| Source validation | 0.879 / 100 | Independent source masks/identity/aggregate checks, retained |
| Authorized machine enumeration | 0.181 / 100 | Repeated sorted DataFrame iteration |
| JSON rendering | 0.024 / 1 | Full unchanged response, no projection reduction |

These sections overlap and must not be summed. Transaction calls are counted, not wire
packets. Source validation is significant but smaller than graph transactions and API
snapshot discovery in this fleet. Prediction/policy lookup is not the dominant work.
The full response still contains 4,860,611 bytes; JSON rendering alone is a small share.
Client reception/decode and resource measurements are retained separately.

The accepted Phase 7 63.410s observation has different run conditions and is not this
study's optimization baseline. Host state/caches/workload can explain much of the
difference before any optimization. Only fresh matched unchanged/candidate blocks can
support a Phase 8 comparison.

Admit **one metadata-index candidate**: build immutable machine descriptors and snapshot
eligibility once from startup-verified tables. Preserve fresh response dictionaries,
all API authorization and graph readiness checks, and exact ordering/UTC strings.
This targets the measured repeated discovery work without touching scientific logic,
graph queries, source validation or complete report serialization. It exchanges startup
work and memory for reduced warm repeated enumeration. Full report caching, graph query
batching, source-index rewrites, frontend caches and increased concurrency are deferred.
Their potential benefit is not established by this candidate's measurements.

Detailed raw traces and bounded builder cProfile statistics are in
`artifacts/phase8/study/baseline_profile_corrected/`. cProfile applies to individual case
construction only; fleets use explicit timers without cProfile. HTTP comparisons install
neither instrumentation nor cProfile. Allocation and Cypher plans are separate diagnostics.

Official driver guidance supports explicit database selection, measured transaction
overhead and EXPLAIN/PROFILE inspection. The accepted adapter already specifies `neo4j`
and read access; this is not a newly implemented gain.
[Neo4j performance recommendations](https://neo4j.com/docs/python-manual/current/performance/),
[managed transactions](https://neo4j.com/docs/python-manual/current/transactions/).
