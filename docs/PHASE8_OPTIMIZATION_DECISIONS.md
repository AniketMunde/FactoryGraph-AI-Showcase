# Phase 8 optimization decisions — 2026-11-15

**Retain C1 as an opt-in native metadata-index implementation**, subject to the final
passing regression/preservation evidence in `results/phase8.json`. Keep the accepted
Phase 7 server and all its source/results unchanged. This decision concerns historical
decision-support service cost, not model quality or replacement of LightGBM.

| Candidate / alternative | Measured basis | Decision |
|---|---|---|
| C1 startup machine/snapshot indexes | Repeated metadata discovery consumed 3.838s of the 9.813s profiled fleet; all three matched fleet pairs improve 40.4–41.1% with exact responses | Retain the new opt-in subclass |
| Graph query batching | 701 managed read calls per full fleet remain significant; existing plans use indexes | Defer; no batched-query code or claimed gain |
| Source-selection indexes | Source validation costs 0.879s per profiled fleet and is an integrity requirement | Defer; validation remains unchanged |
| Reduced provenance / summary projection | JSON render only 0.024s; dropping facts would change semantics | Do not modify complete responses; no new summary endpoint |
| Alternative serializer / driver extension | No isolated candidate measured; dependency changes unnecessary for C1 | Defer; preserve dependency versions |
| Increased workers / compute concurrency | Shared builder has mutable `last_timing`; independent reentrancy not established | Keep one worker / one compute operation; preserve 503 |
| Frontend response caching | Session, credential, generation and failure semantics need separate review | No new frontend cache; original UI remains unchanged |

C1 derives tuples of machine/model descriptors and per-machine ordered snapshot strings
and eligibility from fully verified source metadata, temporal membership and approved
prediction keys. Every runtime has an identity derived from mode, registered config and
the full accepted input-hash mapping. Descriptors live only for that service generation.
Fresh response dictionaries prevent callers mutating cached data. Restart performs full
verification and reconstructs indexes; no hot reload or cross-generation reuse exists.

The indexes contain no reports, facts, predictions or failed responses. API authorization
still runs before requested-machine metadata and case access. Viewer scope remains
machine 17, including snapshot routes. Case/fleet requests retain graph readiness and
every original source/temporal/rule check. A changed graph marker, corrupt source fact or
future context cannot be hidden by successful cached metadata. All report fields and
HTTP response structures remain unchanged. Gallery continues through the original
saved-case path, with no live indexes or silent fallback.

Admission was fixed before matched comparisons: all three full-fleet pairs faster,
median paired reduction ≥20%, pooled reference median regression ≤10%, zero semantic
or security failures, within resource caps. Observed paired median fleet reduction is
41.03%; pooled reference median improves 34.13%. All 59 accepted complete/evidence-only/
abstained reports match, the independent source oracle passes, and 198 saved HTTP
semantic bodies match across repeats/variants. Expected invalid/forbidden/unsupported
responses remain present; busy admission remains one 200 / two 503 per cohort.

Cost: median engine initialization rises 3.167→5.913s; median sampled warm peak RSS rises
1,009,844,224→1,050,312,704 bytes. This is worthwhile for repeated warm replay on the
measured laptop, not automatically for short-lived gallery or serverless workloads.
Cold-helper readiness rises 5.677→9.025s. No real production capacity/SLA is established.

Negative evidence is preserved. The first profile attempt found a harness expectation
mistake for an off-grid source timestamp (404 was correct). The independent recomputation
initially compared the concurrent machine-17 response to a different saved non-alert
machine-1 request; correcting the key to its identical warmup request restored exact
hash equality without changing or rerunning measurements. No slow request was removed.

After measurements, only the Phase 8 administrative preflight helper was adjusted for
fresh output directories and append-only shared-document validation. An amendment
records before/after hashes and identical ASTs for measured budget/config/resource
functions. C1, the HTTP harness, API/UI and all six timing blocks remained unchanged.
No second optimization was admitted to improve the headline result.
