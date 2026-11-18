# MetroPT-3 separate forecasting registration — 2026-11-12

Registered after inspecting actual source cadence/gaps, before any real-data model metrics.
This measured railway compressor stream is a separate study, not an Azure fleet extension.

Official UCI dataset 791 / DOI 10.24432/C5VW3R, CC BY 4.0. The acquired archive SHA-256 is
`aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a`.
It contains 1,516,948 rows spanning 2020-02-01 to 2020-09-01 03:59:50. Actual median cadence
is 10 seconds (9–13s jitter common), contradicting a naive interpretation of the documented
1Hz logger. There are 331 gaps >60s, largest 172,918s, with no duplicate or decreasing times.
No raw cell is missing, but absence of rows is substantial missing temporal coverage.

Analog targets: TP2, TP3, H1, DV_pressure, Reservoirs, Oil_temperature, Motor_current.
The remaining COMP, DV_eletric, Towers, MPG, LPS, Pressure_switch, Oil_level and
Caudal_impulses fields empirically contain only 0/1. They are retained in the raw audit but
are not forecast analog targets or invented component relationships. Stream ID 1 is only
a computational identity for this one APU, not one member of an invented Azure-like fleet.

Resample analog channels using hourly means over [T-1h,T), labeled at T. Require >=270
measurements per bin (75% of the approximately 360 expected at empirical 10s cadence).
Otherwise mark the bin missing; never interpolate or forward/backward fill. The whole
archive produces 5,116 hourly bins, 996 invalid under this rule. Retain raw hashes and
hourly coverage counts. The source has no timezone offset; UTC is explicitly assumed.

The Azure 168h-complete context would yield zero eligible April–August origins. A
coverage-only feasibility audit finds 123 eligible 24h-context/24h-horizon origins on a
3h grid, versus 296 for 24h-context/3h-horizon. Before metrics, register **24h context,
24h primary horizon, 3h origin stride** to preserve the primary horizon and enough valid
history without filling gaps. The shorter context and resampling are differences from
Azure and must be disclosed. Context ends strictly before issue T, including a conservative
one-bin delay relative to the most recent completed hourly aggregate.

Training-only MASE scales: observations before 2020-03-01 with timestamp-aligned lag24h.
Validation: March 2020. Test: April 1 through September 1 exclusive. Require every context
and target bin valid and the complete target horizon within its calendar period. Save all
eligible/excluded origins before inference. Evaluate the whole registered eligible cohort;
it is a coverage-limited real-data backtest, not continuous full-stream validation.

Use the same genuine pinned Chronos-2 checkpoint, CPU/GPU smoke, quantiles, point forecast,
three classical comparators, timing instrumentation and resource gate as the Azure study.
All seven channels form one multivariate group. Do not optimize configurations on test
results. The initial bounded pilot uses the first four validation origins; no failure
enrichment. Then admit all eligible validation/test origins if pilot resource projections
fit 1800s / RAM/disk limits. Preserve partial evidence on failure.

UCI provides four coarse reported air-leak intervals: Apr18 00:00–23:59, May29 23:30–May30
06:00, Jun5 10:00–Jun7 14:30 and Jul15 14:30–19:00 (2020). Maintenance notes and report IDs
contain ambiguities; retain their original wording through the downloaded UCI metadata.
They are not pointwise anomaly ground truth or an independently audited failure log.
This experiment reports forecasting metrics only; it does not claim validated real-world
anomaly detection or fabricate maintenance/graph entities. Azure anomaly feature export
remains separate. No shared raw-unit scores are pooled across these two datasets.
