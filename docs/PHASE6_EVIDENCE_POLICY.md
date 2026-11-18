# Phase 6 evidence and availability policy v1 — registered 2026-11-14

For machine M and timezone-aware UTC snapshot T, every dynamic source fact must have
event_timestamp < T. Apply the same cutoff to every peer event. Fixed machine/model
metadata is assumed known at study start. Source rows have no measured arrival times:
immediate event-time availability and UTC interpretation remain explicit assumptions.
The modern checkpoint/model/artifact creation time is audit lineage, not source arrival.

Reuse Phase 4 event IDs, source row ordinals, file/payload hashes and dataset revision.
Verify each fact against its canonical source row before inclusion. Exclude graph catalog
artifacts, complete-file summaries, future events and unfiltered topology from evidence.
Same-model peers are recorded category associations, not physical dependencies. comp1–4
are categories, not identified installed parts. Distinct failure and maintenance records
sharing a key remain distinct records, not asserted separate physical incidents.

Historical count queries retain their exact window definitions. Aggregate IDs identify
query/window and contributing visible source IDs. Counts can exceed displayed bounded
facts; report truncation explicitly. A failed graph query is unavailable, not zero.
Source mismatch, future-dated facts, missing provenance or inconsistent identities invalidate
the entire returned graph bundle and cause evidence-based rule abstention. No fallback.

Primary risk uses the verified Phase 1 test predictions, with exact Phase 5 A0 parity.
Keep the original threshold 0.9996602309282403, September selection, 24h horizon and 24h
greedy cooldown. No new risk bands. The original episode process starts at the test split
boundary; it is not a continuous live cross-split alert history. Report row threshold,
new episode and suppression separately. Do not expose prediction labels, label_end,
next_failure, future evaluation outcomes, retrospective lead times or future event IDs.

Original 57 input features are clearly separate from supplementary Chronos context.
Forecast issue <= T; source and realized residual observation < T. Read exact accepted
temporal rows only. Undefined forecast statistics remain null, with explicit availability
and valid residual counts. Historical absence cannot be repaired using a later forecast.
No anomaly threshold, severity band, replacement predictor or failure diagnosis is added.

Reports record stable case IDs, input/policy/config hashes, graph build/schema/namespace,
temporal file/model/checkpoint identity, evidence/rule IDs and availability states. Every
recommendation requires human review. Invalid primary artifacts suppress primary risk
recommendations. Missing context does not nullify an otherwise verified model/policy, but
it yields degraded status, data-verification guidance and no unsupported specific action.

The service is retrospective synthetic decision support, not a forecast of a current
real machine. No specific repair, shutdown, cost, parts list or exact failure time is
supported. Historical associations and residual magnitude cannot establish root cause.
