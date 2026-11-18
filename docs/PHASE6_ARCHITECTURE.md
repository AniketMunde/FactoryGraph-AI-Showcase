# Phase 6 architecture v1 — registered 2026-11-14

Implement an offline, deterministic Python library and CLI. No HTTP server, dashboard,
external LLM, autonomous agent, actuation or maintenance-system writeback is included.
The approved Phase 1 calibrated LightGBM remains the only primary predictor. Phase 5's
NO-GO decision remains binding. Replaying a saved probability does not establish live
industrial validity. Research artifacts identify audit lineage, not observations in 2015.

Components and boundaries:

1. PredictionReader verifies accepted manifests and exact A0 reproduction parity before
   reading only machine/time/probability. It supports primary replay on the accepted test
   split. No model retraining, rescoring, threshold fitting or future labels enter the API.
2. PolicyEvaluator reuses Phase 1's greedy 24h episodes over the complete accepted test
   sequence, resetting at its original split boundary. Row threshold, episode and cooldown
   are separate outputs; priority is a review category, never a new probability band.
3. HistoricalEvidenceRetriever uses the existing parameterized Phase 4 historical interface
   in read-only transactions and the accepted namespace. Own facts use [T−720h,T), bounded
   to 100 records in canonical chronological order. Own lifetime counts, model peers and
   peer-window counts are separately named aggregates. Static metadata is source-checked.
4. TemporalContextReader selects exact-key accepted snapshot inputs and Phase 5's 40-column
   Chronos context. It reads no labels or next-failure columns. Supplementary context never
   changes the approved probability; native missing history becomes explicit null.
5. EvidenceValidator checks retrieved records/aggregates against independently masked
   canonical source rows, validates provenance and strict clocks, and rejects conflicts.
6. DecisionRuleEngine emits only seven fixed, versioned human-review suggestions.
7. RecommendationFormatter uses fixed templates; no free-text user or source instructions.
8. ProvenanceRecorder records hashes, stable IDs, schema, namespace and availability policy.
9. CaseReportBuilder assembles validated structured reports, preserving unavailable states.
10. OfflineEvaluationHarness compares source facts, model-policy decisions, deterministic
    output, fault behavior and separate measured timings on preregistered cases.

ArtifactRegistry verifies frozen file digests on service initialization, then serves a
read-only in-memory snapshot for that service lifetime. A fresh service verifies files
again. Integrity manifests detect drift; they are not signatures against malicious
replacement of both files and trusted registrations. Credentials stay environment-only.
Service memory can include complete immutable source/cache tables; only eligible selected
facts enter a case. The full graph signature is checked before/after the study, not used
as historical explanatory evidence. No graph writes occur in the service.

Primary probabilities are available only for accepted October–December test snapshots.
August calibration is not an independent prediction study; September selected the policy.
Earlier accepted snapshots can return evidence-only context, with primary risk explicitly
unavailable. Unsupported times never borrow a nearby prediction or feature row. Malformed
times fail clearly. Unknown machines abstain. Infrastructure failures are unavailable,
never empty history. There is no silent source-table fallback in v1.

The service returns a typed report through CaseReportBuilder.build(machine, snapshot).
Its bounded fleet method accepts a snapshot and at most 100 exact accepted test identities.
Frozen report content is deterministic; timings are evaluator-only nonsemantic metadata.
Phase 7 may wrap this API later, only after separate authorization and security review.
