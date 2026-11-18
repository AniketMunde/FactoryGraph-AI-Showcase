# Phase 7 test and performance protocol v1 — 2026-11-15

Freeze this protocol, architecture, security policy, API request contracts and runtime
configuration before acceptance/performance runs. Preserve all Phase 1–6 source, locks,
scientific outputs and graph identity. This is engineering validation, not a new model
experiment. Docker is absent on this host; container build/start/restart/Linux acceptance
must remain incomplete unless genuinely executed. Native verification cannot replace it.

Full mode uses the exact Phase 6 CaseReportBuilder, no result cache, one API worker and
one in-flight computation. Bearer credentials are server-side secret files. Viewer access
is restricted to machine 17; operator access covers the accepted synthetic fleet. All
data routes require authentication. Unknown parameters, invalid UTC, paths, oversized
bodies/fleets, forbidden origins and unauthorized objects must fail with sanitized errors.
Gallery is an explicitly selected saved-case mode and never a dependency-failure fallback.

Native acceptance uses an actual Uvicorn HTTP server and genuine accepted Neo4j. Verify
machine 1 at 2015-10-16T12:00Z (new episode), the first accepted cooldown example, machine
17 at 2015-10-15T00:00Z (non-alert), machine 1 at 2015-01-08T00:00Z (evidence only), and
unsupported/unknown requests. Compare complete projected reports with Phase 6, removing
only registered internal artifact-path fields. Test validated historical telemetry < T,
event pagination, schema, no outcome fields, authentication, authorization and failures.
Use Streamlit AppTest against the real authenticated HTTP API for every dashboard page;
also start the real Streamlit HTTP/WebSocket service. Browser rendering is recorded only
if actually observed; simulated AppTest rendering is identified separately.

Performance cohort: service startup/shutdown; the four known supported cases once each;
five sequential machine-17 requests; three simultaneous requests (bounded busy rejection
is expected); a 3-machine fleet and one 100-machine fleet at October 15 midnight. One
120-second deadline applies. Timed-out work keeps its slot until its read-only thread
finishes; no unbounded queue/background job is created. Fault injection tests graph loss
and a deliberately short deadline without modifying accepted data or stopping its graph.
Measure HTTP wall, underlying Phase 6 timings, frontend AppTest interaction, RSS and local
database RSS where available. These are descriptive measurements, not an online SLA.

Run unit/security tests in Phase 7; genuine integration with opt-in; all applicable prior
regressions in unchanged environments. Validate Docker/static config and an isolated graph
bootstrap design, but report actual container stages unexecuted if unavailable. Freeze
final implementation/test hashes, command logs, exact outcomes, inventory and preservation.
No public infrastructure, account creation, uploads or public endpoints are authorized.
