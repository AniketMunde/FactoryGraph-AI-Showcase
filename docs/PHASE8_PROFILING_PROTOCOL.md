# Phase 8 native service profiling protocol v1 — 2026-11-15

Register this protocol, YAML, original source/lock/input hashes, hardware/software and
exact request cases before profiling or benchmarks. Decision-support historical replay
is the workload. No model training, neural inference, GPU work, public deployment,
Docker/WSL installation, graph writes/index changes or scientific-output changes.

Gate A verifies every Phase 7 inventoried source identity, its artifact manifest, all
3,555 protected historical files, graph signature/counts and approved prediction/policy
hashes. Extend preservation to immutable Phase 7 source, tests, configuration, locks,
reports and artifacts. Exclude only mutable API/UI logs and active process records.
The four shared chronological documents are separately snapshotted before additions.
Use the unchanged CPU Phase 7 environment. Record CPU, available/total RAM, disk, OS,
package versions, graph version, graph indexes and running API/UI/Java processes.

Requests: all 59 registered Phase 6 cases for exact direct-engine semantic equivalence,
plus the four Phase 7 reference examples (new alert, cooldown, non-alert, early missing
forecast); the first Phase 6 boundary case for evidence-only; API unknown machine and
unsupported timestamp (404), invalid credentials (401), viewer machine 1 (403) and
viewer machine 17. Unknown machine remains an engine abstention, while the accepted
full HTTP contract rejects it. Small fleet is machines 1/17/42; full fleet is 1–100 at
2015-10-15 midnight UTC. No cases selected by timing or future outcome.

Gate C first profiles the unchanged API/engine with bounded cProfile and explicit timers
on all four references, boundary evidence-only, unknown/unsupported requests, a small
fleet and one full fleet. Profiling overhead is measured separately and excluded from
matched performance claims. One tracemalloc reference request is a distinct allocation
observation, not an uninstrumented latency sample. EXPLAIN all fixed historical read
query classes; PROFILE one representative HISTORY and PEER_COUNTS query, with 5s
query limits, read transaction mode and explicit database. Never change original indexes.

Instrumentation separates authentication, endpoint execution, machine authorization
metadata lookup, exact snapshot discovery, prediction/policy, graph session construction,
managed read/query retrieval, independent source validation, temporal lookup, rule
evaluation/validation, report schema construction/validation, provenance and JSON render.
The outer ASGI wall, first/final response-send times and HTTP client headers/body/decode
times are recorded. Graph read includes transaction checkout/retry/round trips; session
construction alone is not connection acquisition. Routing/parsing residual also includes
framework/middleware overhead. Nested/overlapping sections must not be summed into an
invented end-to-end total. Count managed transactions and query calls; wire packets are
not claimed measured round trips. Fleet `last_timing` describes only its final case.

Only after measured bottleneck ranking may one candidate be implemented. Freeze its
hypothesis, exact code hashes, cache/verification contract and admission evidence before
matched comparisons. Permitted candidate classes: immutable metadata/source indexes,
equivalent parameterized read batching or equivalent JSON serialization, one at a time.
No removal of source validation, facts, provenance, ordering, clocks or API fields. A
candidate is opt-in under Phase 8; Phase 7 source and baseline behavior remain unchanged.
Do not increase concurrency or worker count. No full report caching or frontend cache
change is admitted without a separate hypothesis and registered contract.

Matched run order: **B,C,C,B,B,C**, three adjacent baseline/candidate pairs with reversed
middle ordering. Each block uses a fresh one-worker API process on loopback port 18081,
two identical non-alert warmups, five repetitions of each four reference cases (20
requests), boundary/unknown/unsupported/viewer/auth controls, three small-fleet requests,
one full-fleet request and three simultaneous non-alert requests. Requests are identical
across variants. Busy 503 is correct bounded behavior, not failed safe throughput.
Persist canonical reports from every success and compare complete semantic objects;
only HTTP request IDs/timers may differ. No full-fleet warmup: first fleet materialization
and cache/index costs are included. Startup and graceful ASGI close are timed separately.

One service at a time for matched runs; existing idle Phase 7 processes are inventoried
and held constant. CPU comparison uses worker CPU deltas within the defined serial HTTP
window, not process-lifetime counters. Report throughput as successful serial requests /
window wall, and separately accepted concurrent requests / cohort wall. Sample worker
RSS/available RAM at 100ms, retain baseline and peak sampled RSS; sum table deep sizes
only as logical allocations (shared data may overlap). No isolated DB CPU attribution.

Budget: at most 1800s for each profiling/comparison stage, 120s per request, 2GiB maximum
service RSS, 1GiB minimum available RAM, 5GiB minimum free disk. Check between requests
and sample during full fleets; stop and save partial records on exhaustion or two
unexpected infrastructure failures. CPU load and competing process CPU deltas are
observations, not a claim of an isolated workstation. Do not terminate unrelated jobs.
Native process startup deadline is 60s, normal graceful close deadline 15s; failures
remain evidence. No silent reruns, sample removal, threshold changes or deadline tuning.

Retain only if full case/security/temporal/fault parity passes; all three paired full
fleets improve, median paired fleet reduction is at least 20%, and reference HTTP median
does not regress more than 10%. These are local engineering admission criteria, not
significance tests or production SLAs. Report each pair and variation, n/median/max and
p95 only for reference groups with n≥20 (descriptive). Full-fleet n=3 per variant has no
useful tail estimate. Failure samples stay in raw records and invalidate admission when
unexpected. Independently recompute metrics from saved request records and body hashes.

Finally run all applicable previous environment regressions, new genuine Neo4j/API tests,
package/lint checks and historical/graph/source preservation. Preserve negative candidates
and unresolved query/frontend/concurrency alternatives without speculative rewrites.
Docker and real-browser visual/accessibility QA remain open Phase 7 acceptance items.
No subsequent phase starts automatically.
