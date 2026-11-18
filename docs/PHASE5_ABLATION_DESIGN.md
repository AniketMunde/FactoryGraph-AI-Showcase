# Phase 5 fixed ablations — registered 2026-11-13

| ID | Features | Numeric/input column count |
|---|---|---:|
| A0 | Original57 tabular | 57 |
| A1 | Tabular +40 cheap temporal | 97 |
| A2 | Tabular +40 Chronos temporal | 97 |
| A3 | Tabular +27 accepted graph | 84 |
| A4 | Tabular +27 independent relational equivalents | 84 |
| A5 | Tabular +cheap temporal +graph | 124 |
| **A6** | **Tabular +Chronos temporal +graph** | **124** |

A6 is the prespecified primary combined system, not a winner selected from test results.
Primary contrasts: A3−A0, A3−A4, A2−A1, A6−A3, A6−A2, A6−A5, A6−A0.
Graph/source control uses identical ordered numeric definitions/names; equality must
hold on all rows before training, including NaNs. A3/A4 models are fitted independently;
identical results imply value of the information, not a benefit caused by graph storage.

Use the exact accepted split populations and labels: train162798, calibration23945,
validation23146, test72633. No exclusions; missing histories use fixed native-NaN policy.
Exact joins require unique machine/time keys and preserve source order/labels. Save new
matched datasets and hashes without touching prior snapshots or features.

All seven independent LightGBM fits reuse the accepted fixed policy:200 trees, learning
rate.05,31 leaves,min_child_samples100,L2=1,threads4,seed42,deterministic/force_col_wise,
binary objective; model_code is categorical. No hyperparameter search, early stopping or
test-derived feature subset. A0 is a separate reproduction artifact; never refit/overwrite
the accepted checkpoint. Compare its predictions with the accepted frozen baseline.
No stacking or OOF base-prediction meta-model is used: the pretrained forecaster has no
local neural training and its historical outputs are input features, not failure labels.

Fit sigmoid/logit logistic calibration (C=1,lbfgs,seed42) only on August calibration.
Choose primary threshold using the existing conservative validation1% row-budget function
and24h cooldown. Before test evaluation freeze secondary validation0.5%/2% budget thresholds
and the original Phase1 numeric threshold as a descriptive calibrated-policy sensitivity.
The latter can have different alert volume across calibrators; primary fair comparison
uses the shared validation1% budget. Freeze every model/policy/test prediction before
reporting any new test result. Preserve all A0–A6 outcomes; no outcome-driven reruns.

Evaluate calibrated AP,ROC-AUC,precision,recall,F1,Brier,log-loss,ECE/calibration bins,
Phase1 opportunity-based failure-event recall/lead time, false episodes and exposure.
Machine/timestamp-distinct failures preserve the original event definition, collapsing
simultaneous component categories only for that operational identity. Retain explicit
event IDs, component records and model-specific hit/lead information for overlap analysis.

Paired cluster bootstrap:200 machine-resampling draws,seed42,percentile95% intervals for
AP/Brier/event-recall differences. Reuse identical machine draws across all models;
do not treat overlapping rows as iid. No multiplicity-adjusted confirmatory claim.
Report per-machine and monthly variation, descriptive fixed-policy sensitivity, event
overlap and incremental feature-family gains/correlations. Attribution is not causation.
Training-only importance/correlation audit is descriptive, never feature selection.

GO for predictive fusion requires A6 to improve both AP and event recall over A0 with
paired95% difference intervals excluding0 in the favorable direction, and no increase
in false episodes at primary policy. Otherwise NO-GO for replacement (possibly
inconclusive), irrespective of any ablation's isolated higher metric. This conservative
decision is preregistered. Synthetic/public/already-observed test limits all conclusions.
Optional augmented Kumo is deferred; the accepted genuine standalone result stays intact.
