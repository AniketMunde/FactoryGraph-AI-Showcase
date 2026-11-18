# Operations Console v2 — design registration, 2026-11-16

An additive local product-experience milestone. The accepted Streamlit interface,
research evidence, original B API, A0 predictor, frozen policy and graph stay intact.
No incident register, live operating status or maintenance writeback is introduced.

The primary flow is Fleet → selected machine investigation → sensor/source evidence →
deterministic human review → exact verified JSON export. Seven compact workspaces are
Fleet Overview, Assets, Alert Investigation, Machine Intelligence, Knowledge Graph
Evidence, System and Provenance, and Research Information. Selection is shared through
navigation and URL state: machine, exact supported UTC snapshot, tab and evidence ID.

The shell uses a 244px collapsible deep-navy sidebar, restrained amber identity accent,
compact workspace header, persistent historical selection toolbar and soft neutral content
surfaces. Typography uses local system fonts, 12–14px dense controls, 20–26px headings
and tabular numerals. Tokens define ink/slate/amber/red, white surfaces, 4/8px spacing,
6–10px radii, thin borders, visible focus and disabled/loading/error states. No external
fonts, decorative imagery, gradients or fictional operating KPIs are needed.

Fleet wireframe: title/action row → six compact verified replay counts → searchable,
sortable paginated machine table → scope/missingness note. Registered metadata rows may
be unscored; only explicitly requested bounded fleet results contribute to replay counts.
The default cohort is three authorized machines. A 100-machine replay requires an
explicit action and displays its cost/loading state. Filters never trigger replay.

Investigation wireframe: bounded case list at left → machine/policy/risk header at right
→ source-backed evidence → rule-tagged human-review suggestions → export. The list is
the selected replay plus requested case, not an invented global incident database.
Machine Intelligence shares the case and provides four synchronized UTC sensor plots
and tabs for errors, maintenance, prior failures, supplementary Chronos and provenance.

Graph wireframe: legend/cutoff/bound → bounded machine/model/event/category/peer projection
→ selectable source-detail drawer. Recorded facts and derived category/peer associations
use different edges and explicit text. No physical connectivity or causal edges appear.

System diagnostics exposes only authorized API readiness/metadata, returned report
identities and operator-only bounded request metrics. Research information stays separate
from investigation and preserves NO-GO, C1 opt-in and incomplete real-data evaluation.

Acceptance requires genuine authenticated API data, exact probability/policy/export
parity, local session/CSRF/resource tests, real Edge screenshots at 1440×900, 1920×1080
and 390px, UTC/Berlin consistency, keyboard checks, original regressions and protected
hash/graph verification. Compilation alone cannot establish acceptance. Bounded visual
checks target accessibility; they do not claim WCAG certification.
