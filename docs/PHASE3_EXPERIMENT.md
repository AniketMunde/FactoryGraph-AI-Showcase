# Phase 3 registered protocol — 2026-11-12

Phases 1 and 2 remain accepted read-only inputs. No fusion, graph, failure classifier,
dashboard or deployment is implemented. No failure-prediction improvement is assumed.

## Gates and fixed choices

A: verify prior manifests, source/report/lock hashes and actual CSV telemetry; preserve
all original files. B: audit official Chronos-2 weights/API/licenses, then install isolated
dependencies and download only weights/config/model card and upstream license. C: genuine
CPU/GPU smoke with output checks, memory and timing. D: bounded validation-only pilot on
the first five machines ordered by SHA-256 of `42:<id>`, with the first four eligible daily
origins per machine in September. E: extrapolate full workload from pilot; admit the full
predeclared population only if under 1800 seconds and memory/disk limits. Record admission
before test inference; never shrink the population midway or choose on test quality.

## Azure forecast task

Raw hourly volt/rotate/pressure/vibration are separate from 3-hour Phase 1 snapshots.
Use 168 hourly observations **strictly before** issue time T (last observation T-1h).
Predict target timestamps T,...,T+23h, recording leads 1,...,24 relative to the last observed
sample. This conservative availability convention matches Phase 1's features-before-T rule.
The primary horizon is predeclared as 24 hours for maintenance relevance, not optimized on
test scores; report prefix horizons 3/12/24 as secondary forecasting diagnostics. The
existing binary failure task remains unchanged. Point forecast is the median; request
0.1/0.5/0.9 quantiles. Treat each machine's four channels as one multivariate group, with
cross-learning between independent origins disabled. No future covariates or neural fit.

Use origins on the UTC daily midnight grid for forecasting evaluation. Validation is
September 2015; test October–December 2015. Require a complete finite hourly context and
all 24 targets, with the final target strictly before the period end. Gaps cause exclusion,
with reasons/counts saved; no interpolation or silent population changes. Context can cross
period starts because those observations are historically available. Persist forecasts
without actual targets before joining future ground truth. Comparisons use identical keys.

Baselines: persistence; last-24h historical mean; seasonal naive with 24h period. The
period is a registered operational comparator, not evidence that the data are seasonal.
All use the identical context. MASE denominators use only pre-August telemetry and the
mean absolute seasonal difference at lag 24, separately per machine/channel. Zero scales
are undefined, not replaced with arbitrary constants. Report MAE/RMSE/MASE per channel,
machine and prefix horizon; Chronos pinball loss, 80% interval coverage and width.
SDK internal normalization uses context only. No external fitted scaling/imputation.

## Historical anomaly scoring and export

Two independent score families: absolute deviation from the previous 168 observed hours'
median, divided by 1.4826*MAD (context-only robust floor); and absolute errors of **previously
issued** Chronos forecasts normalized by each forecast's historical context MAD. Residuals
become available only at their target timestamp. Collapse overlapping forecasts by latest
eligible issue for each machine/target/channel; no future realization or failure annotation
is ever consulted. Select 99th-percentile per-channel score thresholds on September only,
then freeze before October–December scores. Train-period export thresholds must never use
September: this run exports test snapshots only and records that eligibility limit.

Export separately against exact existing Phase 1 test snapshot keys. At snapshot T, use
observations and completed residuals strictly before T. Use the latest forecast with
issue <=T and source max < issue; future predictions/uncertainty are valid model outputs,
not realized targets. Record forecast trend, predicted variability, interval width, relative
change, latest/24h mean/max residual scores, anomaly fraction/count and run-length persistence,
plus robust-observation score features. Preserve missing scores and staleness where daily
forecast issuance leaves incomplete coverage. Never pretend daily issuance is 3-hour issuance.
Every row carries machine, snapshot, latest source observation, latest residual observation,
forecast issue, model/checkpoint ID and computation-config hash. A per-column feature
contract permits later keyed joins to either tabular adapter, with no classifier fit now.

## Real-data study

Download and audit official UCI MetroPT-3 separately. Determine empirical cadence and gaps,
retain binary channels as states and analog channels as targets. Register a separate
chronological protocol only after inspection, before real-data metrics. Failure intervals
are coarse reports, not pointwise anomaly truth. If no real inference is run, explicitly
mark the real-data evaluation incomplete. No Azure fleet ontology is invented.

## Resources, artifacts and limits

GPU fp32 weights, context 168, four targets per group, up to 16 origin groups per batch,
CPU threads four. Genuine smoke determines compatibility; no automatic device fallback.
Record cold load/import, context preprocessing, synchronized SDK predict, neural forward
when instrumentable, postprocessing, total pipeline, throughput, RSS and CUDA peaks.
The preflight found RTX 3050 6GB, about 12.8GB available RAM and 38.8GB disk. A successful
pilot permits full evaluation but is not itself full evaluation. Stop on <3GB free RAM,
<2GB free disk, failed outputs or 1800s projected/actual runtime; retain partial evidence.

Save protocol/config/membership/input/checkpoint hashes, frozen predictions, actual joins,
metrics, anomaly thresholds/scores, causal exports, runtime and failures under Phase 3 paths.
Regression and temporal perturbation tests must pass; recompute metrics from saved forecast
and actual files without rerunning a model. Previously observed failure benchmark results
do not constitute a fresh confirmatory holdout. Keep negative findings and optional work
clearly distinguished from completed genuine-model experiments.
