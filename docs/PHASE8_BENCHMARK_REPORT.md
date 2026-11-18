# Phase 8 native HTTP benchmark — 2026-11-15

This is matched historical decision-support service replay on Windows 11 10.0.26300,
Intel Core i5-13500H (12 physical / 16 logical CPUs), 34,048,847,872 bytes RAM. Initial
available RAM was approximately 7.2GB and disk space 36.4GB. Python 3.12.10 and the
unchanged CPU Phase 7 environment were used. Exact packages, hashes, Neo4j version and
existing indexes are in the registration. No GPU/neural computation or dependency
installation occurred. Accepted graph: 8,092 nodes / 25,243 relationships, exact original
signature. Existing Phase 7 processes were inventoried and retained throughout.

## Matched measurements

Fixed order **B,C,C,B,B,C**, three adjacent pairs. Each block used a fresh one-worker
Uvicorn process, two warmups, 20 balanced reference requests, seven auth/eligibility
controls, three 3-machine fleets, one full fleet, and three simultaneous requests.
Profiling was disabled in matched blocks. Total comparison wall time was **138.962s**,
below the registered 1800s budget. All successful bodies and expected error records
remain in raw files; no measurement was discarded or repeated for a favorable result.

Primary HTTP seconds include headers, complete body reception and JSON decode on one
persistent HTTPX client. Per-stage header/body/decode times are stored separately.
There are 60 reference requests, nine small fleets and three full fleets per variant.
Each individual reference scenario has only 15 samples; the pooled p95 describes the
fixed four-scenario mixture, not an individual case's tail or a production percentile.

| Metric | Unchanged baseline | C1 metadata indexes |
|---|---:|---:|
| Reference HTTP median / pooled p95 / max | 118.22 / 132.98 / 137.37ms | 77.87 / 105.33 / 116.45ms |
| 3-machine fleet median / max | 0.2986 / 0.3177s | 0.1814 / 0.1884s |
| 100-machine fleet median / max | 9.7857 / 9.8481s | 5.7957 / 5.7964s |
| Full response bytes | 4,860,611 | 4,860,611 |
| Engine startup median | 3.167s | 5.913s |
| Launch-to-readiness median | 5.677s | 9.025s |
| Graceful shutdown median | 0.588s | 0.600s |
| Median sampled warm peak worker RSS | 1,009,844,224 bytes | 1,050,312,704 bytes |
| Worker CPU per fixed serial window, median | 9.203s | 4.125s |
| Completed serial requests/window second, median | 1.868 | 2.734 |
| HTTP 200 serial responses/window second, median | 1.567 | 2.293 |

Serial windows each contain 31 measured requests including the expected authorization/
snapshot rejections, with the full fleet counted as one HTTP request. They exclude
warmups, the concurrent cohort and metrics. CPU deltas are actual worker counters for
these windows; database/client CPU is excluded. These workload-specific rates are not
maximum sustainable capacity. The client deliberately checks resources before each
request, including a 100ms CPU observation; that pacing is inside serial-window wall
time but outside each request's HTTP latency. Concurrent cohort wall also includes
HTTPX client/thread setup. Single-compute admission is unchanged.

| Adjacent pair | Baseline full fleet | C1 full fleet | Reduction |
|---|---:|---:|---:|
| 1, B then C | 9.8481s | 5.7964s | 41.14% |
| 2, C then B | 9.7218s | 5.7957s | 40.38% |
| 3, B then C | 9.7857s | 5.7710s | 41.03% |

All three pairs meet the fixed direction criterion; median paired reduction is **41.03%**.
Reference median ratio is 0.65867. Full-fleet n=3 does not support a useful tail estimate
or broad statistical/generalization claim. No confidence interval or SLA is asserted.

Per variant, 102 serial records include warmups and metrics: 87 HTTP 200, three 401,
three 403 and nine 404, all expected, zero unexpected failures. Every three-request
concurrent cohort returned one 200 and two 503. Median accepted-cohort/window rates
were 2.327 versus 3.117/s, based on three tiny cohorts; no higher concurrency limit or
reentrant service is claimed. All six graceful application-lifespan closures passed.

## Profiling and resource scope

Unchanged fleet ASGI wall was 9.813s in a separate timer pass: snapshot enumeration
3.838s / 100 calls, graph managed read/retrieval 3.888s / 701 calls, independent source
validation 0.879s, machine enumeration 0.181s, JSON render 0.024s. Builder fleet 5.040s
includes graph/source/context/rules and overlaps those timers. Authentication, prediction,
policy, session construction, rules, provenance and schema timers are retained. Session
construction is not full connection checkout; managed-read scope includes transactions,
network waits, retrieval and retries. Call counts are not packet counts.

EXPLAIN inspected five fixed historical query classes; two controlled read-only PROFILE
calls inspected history and peer counts. Existing NodeIndexSeek/NodeUniqueIndexSeek
operators were observed. Database `neo4j` and read transaction mode were already explicit.
No query was changed, no index created and no graph content modified. A graph-query
speedup cannot be attributed to C1. Original seven per-case transactions remain.

A separate tracemalloc case observed 21,014,367 peak traced bytes, 0.296s with tracing
overhead. It is not a matched latency sample. Baseline runtime RSS rose from about
199MB before initialization to 978MB after. Logical deep table sizes include 42.05MB
raw telemetry, 132.31MB predictor inputs and 152.52MB temporal context; shared buffers,
Python indexes and native/library allocations prevent treating their sum as isolated RSS.
The verified source catalog contains 7,966 event facts. Bounded full graph evidence and
response construction still occur per request; no successful/failed report cache exists.

Warm RSS was sampled every 100ms after readiness. Observed block peaks range from
994–1,016MB baseline and 1,046–1,078MB C1, under the 2GiB cap; the lowest observed free
RAM was about 6.85GB, above the 1GiB floor. Startup peaks between checks and short native
allocation peaks are not guaranteed captured. All measured requests remain below 120s.
System CPU point samples vary from 2.9% to 100%; the desktop was not isolated. Existing
process CPU deltas are retained for the broader study period, not each paired window.
Java counters include the study database work. No request was removed for host load.

Full-fleet headers arrive close to body completion: most time precedes first bytes.
Body transfer after headers was approximately 5–6ms on loopback. Decode was about
13–14ms in five blocks and 50.8ms in the final C1 block; that slower sample is retained.
Complete 4.86MB payloads are materially large but serialization/loopback transfer was
not the main measured fleet bottleneck. No provenance reduction is justified by it.

## Frontend and interpretation

A separately registered descriptive AppTest pass exercised all six workspaces against
each actual API. Initial Python/AppTest times were 1.200s baseline and 0.706s C1;
machine-page interactions 1.398s and 1.080s. n=1 per variant, baseline-first order and
shared library/Streamlit warm state prevent claiming a reliable frontend speedup.
Interaction HTTP calls totaled 1.021/0.928s; chart creation 0.351/0.128s. Timestamp/index
transform and response JSON-decode timers are retained. These nested sections overlap;
remaining framework/DataFrame work is not fully isolated. No browser paint was measured.
The original UI still repeats metadata/machine/snapshot requests on reruns and retains
its selected case in session state with manual refresh; no frontend-cache change is made.

The old Phase 7 fleet observation of 63.410s and its AppTest times are historical
references with different host/cache/client scopes. **They are not C1's baseline.**
All before/after claims above use fresh matched unchanged/candidate processes. Windows
native observations do not establish container performance, field benefit or model accuracy.
