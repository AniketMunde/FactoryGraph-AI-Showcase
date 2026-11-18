# Public source workflows

Run at repository root. The illustrative_generated_fixture is only a software/schema
input: no accepted score, source facts or benchmark identity. It is not an offline
replacement engine and neither genuine gallery nor full mode selects it.

## Source and unit tests

Use the README's base venv/install and npm ci/typecheck/test/build commands.
Run Python Ruff lint and format --check. The base lock excludes optional API/UI/CUDA
dependencies, and skips identify unavailable integrations rather than passing them.
For artifact-free API tests create .venv-api, install requirements/phase7-dev.lock
and the editable project with --no-deps --no-build-isolation, then run pytest -q.
Do not enable genuine-integration environment opt-ins.

## Independent baseline acquisition/training

```powershell
.\.venv\Scripts\python.exe -m factorygraph.cli download --config configs/baseline.yaml
.\.venv\Scripts\python.exe -m factorygraph.cli prepare --config configs/baseline.yaml
.\.venv\Scripts\python.exe -m factorygraph.cli train --config configs/baseline.yaml
.\.venv\Scripts\python.exe -m factorygraph.cli evaluate --run-dir artifacts/baseline
```

The downloader uses the pinned upstream Microsoft revision and retains checksums and
its notice locally. Review terms before acquisition/use. A new run is not the original
accepted artifact identity; select fresh outputs, which refuse overwrite.
The Kumo/Chronos acquisition adapters, separate locks and immutable checkpoints are
retained. Their model terms and PyTorch/CUDA requirements apply. No expensive model
experiment is repeated for this showcase.

## Genuine saved gallery

The retained Runtime supports Settings(mode="gallery", gallery_directory=...).
Supply a separately authorized local directory containing its manifest and schema-valid
accepted case files. The default docs/examples/phase6 contains no public cases. Use an
ignored local directory; never copy the software fixture there or call it accepted
evidence. Local API authentication still needs separately generated ignored role tokens.
No genuine gallery acceptance pass is claimed for this public checkout.

## Full application and genuine regression

Full mode needs the accepted registration/policies, all registered inputs, source
telemetry/tables, exact baseline/A0 prediction files, model/calibration/policy identities,
saved temporal context, original Neo4j graph and credentials. See the exact contracts in
phase6/integrity.py:input_paths and phase7/runtime.py. Arbitrary refits or public result
summaries cannot substitute for registered artifacts.
Prior preservation/report-refresh scripts additionally require the original private
evidence tree and original research documents, not rewritten public summaries.

On a provisioned authorized checkout use the retained Phase 7 and console lifecycle
helpers and separately created secret files. They keep credentials server-side.
Full mode rejects missing registration and never falls back to gallery or fixture.
Only opt into genuine tests after prerequisites are supplied. The accepted 174-test
scope cannot be reproduced by source-only unit tests.

Node npm test runs the offline schema test and skips the genuine HTTP workflow.
For separately provisioned local integration, set FG_PUBLIC_GENUINE_INTEGRATION=1 and
run npm run test:integration. That workflow needs authorized original saved cases,
local credentials and the genuine running API/console.

## Docker and lifecycle

Docker/Compose is prepared and unexecuted; an isolated graph, approved runtime bundle,
separate secret files and actual Linux acceptance are still required. No public host
is enabled. The frontend is not bundled in the Python wheel. Stop an owned console
before replacing .next with a rebuild. Never stop another application's process tree.


## Exact optional API environment commands

```powershell
py -3.12 -m venv .venv-api
.\.venv-api\Scripts\python.exe -m pip install -r requirements/phase7-dev.lock
.\.venv-api\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-api\Scripts\python.exe -m pytest -q
```

## Exact separately authorized gallery launcher

Only after obtaining genuine saved cases/manifest and creating local role tokens:

```powershell
.\.venv-api\Scripts\python.exe -m factorygraph.phase7.cli credentials
$env:FG7_OPERATOR_TOKEN_FILE = (Resolve-Path 'artifacts/phase7/secrets/operator.token').Path
$env:FG7_VIEWER_TOKEN_FILE = (Resolve-Path 'artifacts/phase7/secrets/viewer.token').Path
.\.venv-api\Scripts\python.exe -c "from pathlib import Path; import uvicorn; from factorygraph.phase7.api import create_app; from factorygraph.phase7.config import Settings; uvicorn.run(create_app(Settings(mode='gallery', gallery_directory=Path('artifacts/authorized-gallery'))), host='127.0.0.1', port=18082, workers=1)"
```

Without that authorized directory, startup fails. The illustrative test fixture must
not be used there. This launcher has not been counted as genuine gallery acceptance.

## Full native launcher on a separately provisioned host

After the complete registered artifact bundle and genuine Neo4j are installed, create
.venv-phase7 with requirements/phase7-dev.lock and the editable source. Set Neo4j
credentials through local ignored files/session variables. On free native ports:

```powershell
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli credentials
.\.venv-phase7\Scripts\python.exe -m factorygraph.phase7.cli start --mode full
.\.venv-phase7\Scripts\python.exe scripts/operations_console.py credentials
.\.venv-phase7\Scripts\python.exe scripts/operations_console.py start --run-dir artifacts/local-console
```

The full workflow is conditional on authorized exact inputs. These commands have not
been executed against the public candidate and must not target another running demo.
