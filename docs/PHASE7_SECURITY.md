# Phase 7 security policy v1 — 2026-11-15

Local demonstration only: native services bind 127.0.0.1. Compose publishes API/UI ports
on host loopback only; Neo4j has no published port. Hosted mode is rejected by configuration.
Use maintained FastAPI HTTPBearer parsing and constant-time secret comparison, with two
random secret-file credentials: operator (fleet), viewer (machine 17). The Streamlit
server reads its credential from a file; tokens never enter JavaScript, query strings,
downloads, routine logs or committed files. No homemade OAuth/crypto is implemented.
This simple local token model is not a reviewed public identity/session solution.

All data, readiness, metrics and schema endpoints are protected. Only minimal process
liveness is anonymous. Enforce per-object authorization on cases, snapshots, telemetry,
events and fleet requests. Unknown query parameters are rejected. Inputs are typed and
UTC-aware; file paths/Cypher are never request arguments. Strict host/origin checks,
16KiB request bodies, at most 100 unique fleet machines, one computation, a bounded
rate window and 120s response deadline limit work. A timeout does not kill a Python
thread: keep its slot until completion, rejecting subsequent work as busy. No job queue.

Use no-store/nosniff/frame-denial/referrer headers. Frontend XSRF remains enabled. Errors
return safe categories and request IDs, never raw exceptions or registry/filesystem data.
Metrics/logs retain bounded route/status/mode/outcome/duration/dependency fields, not
tokens or source payloads. Initialization rejects incomplete/corrupt required artifacts;
graph loss makes full-mode readiness fail and case routes return explicit 503 degradation,
without silently serving gallery data. Missing temporal context follows Phase 6 semantics.

API graph access uses fixed approved read queries and read transaction mode. Neo4j
Community user privileges do not provide the same role-based controls as Enterprise;
application-level read enforcement is not a database permission guarantee. Separate
Compose graph initialization is an offline administrative step in a fresh volume.

Before public hosting: independent auth/access review, HTTPS, external rate/resource
controls, secret rotation, monitoring, dependencies/image scanning, data/source license
review and operational governance. No public exposure is authorized here.

References: [FastAPI security](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/),
[Neo4j authentication/authorization](https://neo4j.com/docs/operations-manual/current/authentication-authorization/).
