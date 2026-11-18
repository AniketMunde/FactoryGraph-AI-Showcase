# Phase 5 research protocol — registered 2026-11-13

Question: does source-grounded graph history plus genuine pretrained temporal forecasting
improve calibrated24h failure prediction over the accepted LightGBM baseline and cheap
temporal controls? Restrict this experiment to the accepted synthetic Azure fleet. Preserve
Phases1–4, including incomplete MetroPT testing; no Phase6/deployment/agent/dashboard.

Gate1 verifies accepted manifests/source hashes and captures Phase5 historical protection.
Gate2 freezes `PHASE5_TEMPORAL_FEATURE_POLICY.md` and `PHASE5_ABLATION_DESIGN.md`, input
hashes, labels/split membership and daily origin membership before forecast/model results.
Use existing isolated pinned environments read-only: Phase3 for genuine Chronos inference,
Phase4 for genuine Neo4j regression tests, base/Phase3 for fixed LightGBM. No new package
or remote model download is required; record the exact execution environment and locks.

Gate3 pilot: machines[1,17,42,73,100], first four historically eligible daily origins each,
chosen before metrics. Run genuine Chronos, validate outputs/temporal identities and
resource usage, preserve frozen forecasts and repeat check. Admission uses free RAM>=3GB,
disk>=2GB, projected full forecast loop with2x margin+300s feature allowance<=1800s.
Do not change context, quantile ordering or population after observing outcomes. Preserve
failure/partial evidence and report temporal branch incomplete if the gate fails.

Gate4 forecasts all registered historically eligible daily origins on all100 machines,
without future-ground-truth eligibility filtering. Preserve early unavailable rows as
specified. No use of Phase3 September thresholds or its test feature values. Generate
new consistent40-column cheap/Chronos groups across all splits from frozen forecasts.
Gate5 independently reproduce graph numeric values using source-table cumulative/as-of
relational aggregations, compare all27 columns to accepted graph exports, audit feature
clocks/missingness and freeze one matched full-population dataset for every ablation.

Gate6 smoke fits a separate20-tree model on the first historical20000 training rows and
checks held calibration prediction/calibrator/serialization roundtrip; no model selection
or test scoring. Gate7 saves full registration with exact source/policy/feature/model
hashes, A0–A6 contracts,seed42, fixed hyperparameters, frozen split keys and metric rules.
Gate8 executes all seven registered independent fits and August calibration; September
alone fixes alert thresholds. Save/hashes all test predictions before computing new test
metrics. No search, best-seed reporting or outcome-driven restarts.

Gate9 recomputes metrics from saved predictions and checks model reloads, calibration,
keys/labels, all feature/model/policy manifests and causal perturbation tests. Gate10
runs prior/new regressions, rechecks every protected file and publishes all results/costs.
Use machine-cluster uncertainty as registered; exploratory previously observed test is not
a fresh confirmatory holdout. Do not claim real-industrial uplift or graph-storage causation.

Record component timing: shared tabular preparation/reference time, cheap forecast/export,
Chronos load/context/SDK/neural/postprocessing/feature export, graph-cache retrieval and
accepted graph-generation reference cost, independent relational aggregation, join/cache,
each model fit/calibration/load/predict and complete offline path. Report RSS/CUDA/storage,
batch latency/throughput; precomputed warm inference is not a complete online request.
Any tabular pipeline remeasurement writes only Phase5 paths and never regenerates accepted
labels/features in place. Retain one-time versus amortized costs and negative findings.
