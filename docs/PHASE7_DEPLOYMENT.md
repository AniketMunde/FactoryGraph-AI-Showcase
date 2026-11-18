# Phase 7 local deployment — 2026-11-15

This is a synthetic historical engineering demonstration. No public deployment or
real-machinery readiness is authorized. Docker is absent on the implementation host;
the Docker/Compose configuration is prepared and statically checked, **not executed**.
Native Windows API/UI, real Neo4j integration and Streamlit AppTest are separate evidence.

## Native setup and run

Existing accepted artifacts and the original local Neo4j instance must already exist.
Do not rebuild any accepted experiment. Run at repository root. Preserve all prior
environments/locks; Phase 7 uses an isolated CPU-only environment without torch/CUDA.

```powershell
.\.venv\Scripts\python.exe -m venv .venv-phase7
.\.venv-phase7\Scripts\python.exe -m pip install -r requirements/phase7-dev.lock
.\.venv-phase7\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-phase7\Scripts\python.exe -m pip check
# Run once in a fresh Phase 7 workspace; stages refuse to replace audit evidence:
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.audit audit
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.audit inventory
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.audit bundle
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli credentials
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli register
$env:FACTORYGRAPH_NEO4J_USER = 'neo4j'
$env:FACTORYGRAPH_NEO4J_URI = 'bolt://127.0.0.1:17687'
$env:FACTORYGRAPH_NEO4J_PASSWORD = (Get-Content -LiteralPath '.env.phase4' -Raw).Trim()
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli start --mode full
```

Open **http://127.0.0.1:18501**. API process liveness is
http://127.0.0.1:18080/api/v1/health/live; all data/readiness routes require a bearer token.
The dashboard reads the operator credential server-side from its ignored secret file.
Do not copy tokens into the browser or a URL. Generated viewer credentials authorize only
machine 17. The API source, parameter names and statuses are in `PHASE7_API.md`.

For a foreground API instead, set `FG7_OPERATOR_TOKEN_FILE` and `FG7_VIEWER_TOKEN_FILE`
to the generated absolute file paths, then use
`python -m factorygraph.phase7.server`. One worker only. Normal Uvicorn shutdown invokes
the tested lifespan close. The native lifecycle helper stops only its recorded owned
processes; on Windows it uses process termination, not a claimed graceful signal path.
ASGI graceful resource closure is verified independently with the genuine integration tests.

```powershell
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli stop
# Optional explicit saved gallery: no graph queries and no arbitrary inference.
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli start --mode gallery
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli stop
```

Do not switch modes by catching a graph failure. A failed full startup leaves a failure
record/log; stop any owned surviving UI process explicitly before another start. No
Neo4j process, original data, credential or accepted namespace is stopped/deleted.

## Verification and bounded pilot

Run the pilot once after freezing the contract and starting full mode. It preserves its
actual one-pass output rather than replacing measurements. Do not run other expensive
jobs concurrently with that measurement. The test helper then captures actual current
logs, all five environments, dependencies, Ruff and package contents under Phase 7 paths.

```powershell
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.pilot
.\.venv-phase7\Scripts\python.exe scripts/phase7_verify.py
# Final post-lifecycle acceptance used a separate directory, preserving the initial logs:
.\.venv-phase7\Scripts\python.exe scripts/phase7_verify.py --evidence-name final
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.report
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.audit verify
```

The API/UI must be running for the opted-in HTTP/AppTest tests. New clones first need
accepted prior artifacts and registrations; these are deliberately ignored by Git. The
report refresher verifies saved evidence and cannot create missing passing test records.
Repeated development/acceptance attempts retain their logs and are distinguished from
the registered performance run. Source changes after measurement require explicit
provenance review; administrative reporting changes are separate from measured runtime.

## Docker preparation — execution incomplete

The API image installs only `phase7-api.lock`, Python code and versioned Phase 7 config.
The dashboard image installs only `phase7-dashboard.lock` and its API-client/app files.
Both use non-root UID 10001 and version-pinned Python 3.12.10 slim images. The build
context is default-deny; it excludes environments, credentials, datasets, checkpoints
and unrelated experiments. Base-image digest pinning and clean Linux wheel resolution
are not verified without the Docker engine. Do not call these images built or accepted.

The runtime inventory contains **51 files / 193,355,720 bytes**. It includes all registered
Phase 6 inputs, configuration/schema/policy files and gallery examples. It excludes
neural checkpoints and other ablations. Source CSVs and some frozen Parquet files contain
future evaluator information at rest; they are private backend mounts, never frontend
files or static web assets. Phase 6 column whitelists and as-of filters govern responses.
The inventory records category, path, bytes and SHA-256 for each required file.

Before attempting Compose on a separately prepared Docker Desktop/WSL2 host:

```powershell
# Read-only export of the accepted logical graph; never modifies the original:
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.bootstrap export
Copy-Item -LiteralPath deployment/.env.example -Destination deployment/.env
docker compose --env-file deployment/.env -f deployment/docker-compose.yml config
docker compose --env-file deployment/.env -f deployment/docker-compose.yml build --pull
docker compose --env-file deployment/.env -f deployment/docker-compose.yml up -d
docker compose -f deployment/docker-compose.yml ps
docker compose -f deployment/docker-compose.yml logs --tail 100 api dashboard bootstrap
```

Compose creates a **separate** `factorygraph-phase7-demo` graph volume. It publishes only
host-loopback API/UI ports and no Neo4j port. Bootstrap may connect only to the internal
`neo4j` service, validates the accepted snapshot SHA, uses the Phase 4 allowlisted schema
and reconciles all 8,092 nodes / 25,243 relationships / exact logical signature. It refuses
a nonempty different graph. The existing local database is never its bootstrap target.
The API has an independent read-query allowlist and cannot call administrative writes.
Community credentials must not be advertised as database-enforced read-only roles.

Configuration uses read-only minimal bind mounts, secret-file injection, no-new-privileges,
dropped capabilities, memory caps and health checks. The current default health check
for API is liveness; authenticated readiness must also be tested before accepting a
deployment. Verify secret-file permissions, graph image tag availability, Linux paths,
resource use, read-only mounts, restart and graceful shutdown on the actual Docker host.

```powershell
# Stop this Compose project, preserving its data volume:
docker compose -f deployment/docker-compose.yml down
# Removing the isolated demo volume is optional and destructive; inspect its name first.
# Never delete/mount/replace the original Phase 4 runtime data directory.
```

## License and distribution gate

The pinned Microsoft repository's MIT notice was retrieved through the official GitHub
API and retained locally under `artifacts/phase7/legal/LICENSE`. Dataset-specific terms
were not separately established; do not equate this code notice with blanket permission
for every source asset. The project still has no publication license assigned. Full
artifact redistribution and private-repository access require owner review before hosting.
No Kumo/Chronos weights are required or included. Their separate notices remain in the
accepted research records; permissive SDK licensing is not a model-weight authorization.
Neo4j's distribution and dependency notices also require review when redistributing images.

Upstream reference: [pinned Microsoft notice](https://github.com/microsoft/sqlworkshops/blob/e836f4e866028db7fd7d1a66b88f79664a1f4eac/LICENSE).
