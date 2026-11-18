# Public-source validation

Actual source-only checks on 2026-11-18, without private research inputs:

| Check | Result |
|---|---|
| Base Python software tests | 129 passed / 21 skipped |
| API-capable software tests | 152 passed / 25 skipped |
| Node tests | 1 passed / 1 genuine HTTP workflow skipped |
| Ruff lint and formatting | Passed |
| TypeScript and Next.js build | Passed |
| Python wheel/sdist build and installed core imports | Passed |
| Required sdist JSON contracts and independent fixture | Present |
| npm dependency advisory check | 0 known vulnerabilities at check time |

The base run used the existing release-preparation dependency environment; the
API-capable run used the unchanged Phase 7 toolchain with imports from this public
source and no authorized data/model/case inputs. Dependency caches were reused.
These are software checks, not new ML experiments or live-service acceptance.

Skips identify optional packages, absent accepted artifacts, or explicitly opt-in
genuine graph/gallery/native integrations. The accepted 174-test provisioned suite
remains historical research evidence and is not an artifact-free clone result.
The fixture is independently generated, unscored and never a runtime fallback.

The wheel provides Python core; the complete product is source-checkout based.
Docker/Linux, public hosting and real-machinery validation remain unexecuted.
Dependency consistency/advisory checks are not full security certification.
