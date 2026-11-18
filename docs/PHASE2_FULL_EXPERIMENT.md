# Phase 2 full-fleet preregistration

Registered 2026-11-08 **after the genuine-model resource smoke, before any validation
comparison metrics, context selection, or Phase 2 test evaluation**.

The original [pilot protocol](PHASE2_EXPERIMENT.md) remains an immutable record. Its genuine
inference smoke succeeded on CUDA and CPU. Its conservative runtime extrapolation was
approximately 116 seconds for full-fleet validation of both context budgets plus one
selected full-fleet test evaluation. That falls well within the registered 1800-second
budget. Therefore execute the full cohort instead of treating available resources as a
reason to settle for a pilot. The pilot has no validation/test comparison results.

## Fixed full-study choices

- Configuration: `configs/phase2/kumo_full.yaml`; new output path
  `artifacts/phase2/kumo-full/`. All 100 machines and **every original eligible validation
  and test row**. Exact keys and input hashes are saved before inference. No sampling,
  target balancing, altered labels, split changes, or baseline retraining.
- Pretrained NVIDIA Kumo Tabular small classifier at revision
  `3c3e10bbdb590ace29e7026847f92db3c603096d`; official SDK 0.2.1; CUDA fp16 autocast,
  one estimator, cached SDK `fit`/`predict`, 64 query rows/batch, seed 42, four CPU threads.
- Uniform, nested context sizes 512 and 2048 from the entire original training period.
  Sort by machine/time and take the first N indices of a seeded NumPy permutation.
  Require both classes and prove `context.label_end < query_time` for every batch.
  Never use August, September or test labels in model context. Negative outcomes wait
  the complete 24-hour horizon; positive outcomes use the same conservative availability.
- All 57 Phase 1 features; fixed categorical model vocabulary; unknown numeric history
  stays missing. The SDK fits preprocessing/cache state exclusively from context.
- No fitted recalibration. Select context size by September average precision only;
  tie-break to smaller context. Select a conservative threshold for at most 1% September
  alert rows, then persist that policy **before** October–December inference/evaluation.
- The test is evaluated once using the selected context. Context sensitivity is assessed
  on validation only. Phase 1's benchmark test has already been observed; no fresh
  confirmatory significance or test-driven optimization claim is made.
- Reuse the frozen calibrated LightGBM probabilities and original threshold on identical
  rows. Reload its saved model only for matched inference timing and verify reproduced
  probabilities against the saved ones. No LightGBM fit, tune or threshold change.

## Metrics and runtime

Use the Phase 1 snapshot metric definitions plus F1 and TN/FP/FN/TP. Report raw Kumo versus
calibrated LightGBM explicitly, including their different context/training budgets. Report
monthly test diagnostics after freezing the policy; they cannot select new configurations.

For direct continuity, report Phase 1's opportunity-based event recall/lead time on the
complete full-test population. Separately report stricter complete-window event metrics
that require every expected 3-hour opportunity in the preceding 24 hours. Both models
use the identical event cohort for each definition. No event filtering changes row labels.
Do not silently compare the two definitions or modify old reported metrics.

Measure cold local model load, context construction/cache time, query tensor/safety work,
synchronized SDK prediction, instrumented neural-module forward time, total batch and
period times, throughput, RSS/OS peak working set and peak CUDA allocated/reserved bytes.
GPU neural time uses CUDA events at the official neural module's forward hooks; SDK
timing additionally includes its cache preprocessing and output processing. CPU neural
time uses wall time hooks. Feature generation and checkpoint download are separate.
Baseline CPU and Kumo GPU costs are descriptive device-specific measurements.

Repeat the resource gate for this new full configuration before evaluation. Stop explicitly
on a failed smoke, projected time beyond 1800 seconds, available RAM below 3GB, or inference
errors. Preserve genuine evidence and report incomplete status; never shrink the population
mid-run. The predeclared small checkpoint/context budgets are not revisited using outcomes.

Maintain checksum protection for the accepted Phase 1 artifacts, original source modules,
dependency lock, dataset/snapshot manifests, reports and configuration. Save all new
artifacts under Phase 2 paths. No Phase 3/4, dashboard, chatbot or deployment work.
