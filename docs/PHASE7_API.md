# Phase 7 API contract v1 — 2026-11-15

All endpoints use `/api/v1`. Full mode calls the frozen Phase 6 builder; gallery serves
only hash-verified existing reports. HTTP projections remove only the supplementary
context's internal `artifact_path`. Case IDs, calibrated probabilities, policy, evidence,
rule IDs, cutoffs, hashes and limitations remain unchanged. No future outcomes are added.

| Method / route | Contract |
|---|---|
| GET health/live | Anonymous minimal process liveness |
| GET health/ready | Authenticated artifact-initialization and current graph readiness |
| GET metadata | Safe dataset/mode/capabilities/approved model/horizon/limitations |
| GET machines | Authorized machine IDs/model categories; offset, limit 1–100 |
| GET snapshots | machine_id; eligibility primary/all/evidence_only; limit ≤200; exact UTC identities |
| GET cases/{machine_id} | snapshot_time; exact accepted primary or historical-context key; Phase 6 report |
| GET telemetry/{machine_id} | snapshot_time, hours 1–168; actual source readings strictly before cutoff |
| POST fleet/replay | Strict JSON snapshot + 1–100 unique authorized machine integers; primary snapshots only |
| GET metrics | Operator-only bounded request metrics, startup/RSS; no secrets/registry |
| GET schema | Authenticated OpenAPI schema |

Authorization: operator covers registered fleet; viewer covers machine 17. UTC timezone
must be explicit with zero offset. Unknown machines/snapshots return 404; malformed input,
unknown/duplicate query parameters and oversized fleets return 422; unsupported gallery
capabilities return 409. Anonymous/invalid credentials return 401, unauthorized objects or
origins 403, oversized bodies 413, rate limits 429, busy/dependency failures 503 and case
deadlines 504. Unexpected failures return sanitized 500 with request ID. No exception
text, filesystem registry, credential or raw future label is returned.

Legitimate evidence-only and saved abstained reports return 200 with explicit status.
Dependency-degraded reports use 503 and keep the marked sanitized report where available.
There is no fallback to gallery on graph loss. Readiness is not liveness. No caches change
case semantics; the frontend may retain an already displayed response in session state
until refresh, explicitly keyed by machine/time/mode. It never synthesizes new backend data.

One in-flight compute slot is retained until completion, including after an HTTP timeout.
No arbitrary paths, file uploads, Cypher, training, network destinations or maintenance
actions are API parameters. All requests receive no-store and safe response headers.
