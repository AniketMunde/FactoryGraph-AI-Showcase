# Research plan

## Question and hypotheses

Does combining tabular foundation models, time-series foundation models and knowledge-graph
context improve industrial failure prediction and maintenance decision support at acceptable
cost? The null hypothesis is no improvement over a strong causal LightGBM baseline.
An accuracy gain that disappears under leakage controls, equal compute, or calibrated alert
budgets does not support the claim. The synthetic benchmark cannot establish factory utility.

The initial target is machine-level any-component failure in `(t,t+24h]`. Component-specific
models and time-to-event models are future tasks. Snapshots are every 3 hours. No prior
failure feature is used. A contemporaneous failure snapshot is excluded, and incomplete
follow-up at the end of each machine stream is censored. Complete failure logging is assumed.

## Frozen Phase 1 protocol

| Period | Start inclusive | End exclusive | Purpose |
|---|---|---|---|
| Train | 2015-01-08 | 2015-08-01 | Fixed LightGBM fit |
| Calibration | 2015-08-01 | 2015-09-01 | Logistic map of clipped probability logits |
| Validation | 2015-09-01 | 2015-10-01 | Select alert threshold only |
| Test | 2015-10-01 | 2016-01-01 | Held-out reporting |

All timestamps use UTC as an explicit source-clock assumption. Within each period exclude
snapshots with `label_end >= period_end`. Features are not re-fit on validation or test.
The fixed 200-tree CPU configuration is specified before test evaluation. No early stopping,
hyperparameter search, resampling or class weighting is performed in this first experiment.
Sigmoid calibration fits only the calibration period; its metrics are in-sample diagnostics.
Validation policy metrics are selected-period diagnostics. Only test is held-out reporting.

The threshold produces at most `floor(0.01*N_validation)` alert rows. Ties at the boundary
are excluded. The threshold is frozen for test, where the alert fraction can change. A
separate retrospective recall-at-budget metric ranks each evaluated period using its own
scores. It describes ranking quality with a known period capacity, not a deployable threshold.
Once inspected, this test is a development benchmark; future confirmatory claims require a
new frozen holdout or preregistered rolling-origin evaluation.

## Metrics and operational definitions

- PR-AUC is average precision (step-integrated precision/recall), not trapezoidal PR area.
  Also report prevalence, ROC-AUC, snapshot precision/recall and alert fraction.
- Brier score, log loss, ten equal-width reliability bins and expected calibration error
  describe probability quality. Undefined single-class ranking metrics are JSON null.
- A false alert row has no failure in its next 24 hours. Snapshot exposure is
  `N_snapshots * 3 / 24` machine-days, excluding purged/censored opportunities. Report
  false rows per machine-day; this exposure is not continuous monitored uptime across gaps.
- Episodes greedily keep the first alert per machine and suppress following alerts for
  24 hours, regardless of eventual outcome. False episodes use the kept row's target.
- Event metrics deduplicate simultaneous machine failures. A failure is eligible if at
  least one evaluated snapshot falls in `[failure-24h,failure)`. A kept alert in this interval
  detects it; report eligible count, detected count, recall and first-alert lead-time values
  and median among detected events. This is opportunity-based recall, not complete-window
  recall. Undetected events have no lead time, and cooldown can suppress otherwise useful alerts.
- Record training and model-load wall time; warm batch latency p50/p95, throughput, threads,
  process RSS and OS peak working set when available. These are local descriptive measurements,
  exclude feature building, and do not measure GPU requirements or isolated model memory.

## Planned ablations (not run)

| Experiment | Information |
|---|---|
| A | Causal classical LightGBM baseline |
| B | Tabular foundation model on the same allowable snapshots |
| C | Tabular features plus temporal foundation outputs |
| D | Tabular features plus graph features |
| E | Tabular foundation, temporal foundation, and graph fusion |
| F | Matched fusion variants removing each modality in turn |

Keep periods, target, snapshot cadence, label exclusions and operational policies identical.
Match training/context data and report both full-data and context-budget-matched LightGBM
controls for models with context limits. A new modality must not silently change the cohort.
Train fusion on chronological out-of-fold base outputs; never fit a meta-model on test scores.
Compare calibrated and raw scores, log hyperparameter/compute budgets, and preserve negative
results. Use multiple seeds and rolling origins; paired uncertainty estimates should block by
machine/time because overlapping windows are dependent. No row-wise iid confidence intervals.

MetroPT-3 later validates forecasting/anomaly methods on measured sensor data. Its available
failure reports do not supply Azure-like machine/component relationships; no graph transfer
claim or fabricated maintenance schema is permitted. Include simple persistence/seasonal
forecast baselines, MAE/MASE or scaled errors, quantile loss/coverage, and event-aware anomaly
metrics only after its actual sampling and annotations are audited.

## Optimization extension

Once fusion is validated, profile feature building, graph traversal, model load and prediction
separately, then end-to-end. Sweep CPU/GPU, batch size, context length and caching. Compare
latency/throughput/memory against calibrated quality and alert utility. Quantization, pruning
and compression require documented architectural support and matched post-change evaluation.
No such method is implemented or claimed in Phase 1.
