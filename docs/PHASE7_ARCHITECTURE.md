# Phase 7 architecture v1 — 2026-11-15

Browser → Streamlit server → authenticated FastAPI → frozen Phase 6 CaseReportBuilder →
approved saved LightGBM predictions / historical Neo4j / accepted Chronos context. The
frontend reads no research files and never talks to Neo4j. Full mode initializes one
engine per process with FastAPI lifespan and closes its driver on shutdown. One worker
and bounded concurrency protect mutable timing/state and memory. No result caching,
new predictions, training, scheduler, agent, LLM or Phase 8 optimization is introduced.

Runtime modes: full local retrospective replay (primary), verified saved-case gallery
(explicit, no graph or arbitrary inference), public hosting disabled pending review.
Public HTTP projections preserve probabilities, policy, evidence, context, rule and source
IDs, while dropping internal artifact paths. Case IDs and frozen report semantics remain.
Telemetry comes only from verified source rows strictly before the selected cutoff.

The existing wheel is not self-contained. Deployment inventory includes all 43-ish
registered input files (actual count is generated), Phase 6 registration, seven policy/
schema/config files and gallery reports. Neural checkpoints and unrelated experiments
are excluded. Minimal files are staged under an ignored Phase 7 runtime directory and
mounted read-only, never copied wholesale from the private repository into an image.

Frozen Phase 6 config JSON contains Windows path spellings. A new Phase 7 configuration
subclass preserves that serialized identity while using native filesystem Paths; old
registrations and source are never rewritten. Linux parity remains conditional on genuine
container verification. The existing graph connector restricts hosts to localhost, so
Phase 7 supplies an official-driver read-only query-allowlist adapter for the isolated
Compose service hostname. Native mode uses the original localhost graph read-only.
Community account privileges are not claimed to enforce database-level read-only access.

Compose defines separate API/dashboard images and an isolated Neo4j volume with no
published database port. A one-shot bootstrap preserves the accepted graph properties,
identities, counts and logical signature in that fresh instance and refuses nonempty or
mismatched graphs. It must not reconfigure or overwrite the original local database.
The API cannot call bootstrap writes. Docker/WSL availability and Linux dependency/path
parity determine whether this container design can be reported verified.

Reference APIs: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[Streamlit app testing](https://docs.streamlit.io/develop/concepts/app-testing/get-started),
[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
