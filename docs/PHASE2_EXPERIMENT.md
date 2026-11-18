# Phase 2 registered experiment protocol

Registered 2026-11-08 before genuine-model comparison. Phase 1's full-test results have
already been observed; this is an exploratory follow-on benchmark, not a fresh confirmatory
holdout. No test outcome may select context, threshold, preprocessing or calibration.

## Immutable inputs

Read the saved baseline config, feature contract, snapshot manifest and prediction files.
Verify all Phase 1 artifact hashes and prepared data hashes before each stage. Use the
existing 57 features, labels, exclusions, and chronological splits without regeneration.
Phase 1 files and its environment are read-only inputs to Phase 2.

The initial hardware audit finds a 6GB RTX 3050 Laptop GPU, 32GB system RAM (about 11GB
currently available), and 44GB free disk. Install the foundation SDK and CUDA PyTorch in
`.venv-phase2`, with checkpoint files under ignored `data/models/phase2`.

## Registered configurations

Kumo Tabular small classification, checkpoint repository `nvidia/Kumo-Tabular`, pinned
revision `3c3e10bbdb590ace29e7026847f92db3c603096d` (upstream tag v1.0.1), file
`small/classifier.pt`. SDK `structured-data-models==0.2.1`. One ensemble member, query
batches of 64, seed 42, four CPU threads, CUDA fp16 autocast with fp32 checkpoint weights.
No fine-tuning, quantization or pruning. CPU inference is checked separately on a small
genuine-model query. Hardware suitability is conditional on these executable checks.

Context budgets **512 and 2048** are fixed before prediction. Sort all training rows by
machine/time, apply `numpy.random.default_rng(42).permutation`, and use the first N rows.
The contexts are nested and sampled uniformly without class oversampling. Both binary
classes must be present or the experiment stops. Persist context keys and selected labels.
All context rows must belong to the original training period. Require every context
`label_end < min(query_time)` and disjoint machine/time keys before every query batch.
The most recent eligible training label ends before August 1, whereas policy queries begin
September 1 and test queries begin October 1; the implementation verifies the actual maxima.

No probability recalibration is fitted in this registered study. Compare raw Kumo
probabilities with the accepted, already calibrated task-specific LightGBM baseline, and
report that procedural difference explicitly. August calibration data are unused by Kumo.
Native SDK preprocessing may fit only on context features, never future query distributions.

## Bounded population and execution gate

Start with a predeclared **10-machine pilot**, selecting machines by the smallest SHA-256
values of `42:<machineID>` and retaining every original validation/test opportunity for
these machines. Selection uses machine identifiers only, with no target balancing or
outcome inspection. Preserve the same cohort and rows for both contexts and both models.
The configuration and exact membership are saved before smoke inference. A full-fleet
study is a separate registered run; the pilot is never labeled a full-test experiment.

Run a smoke inference using historical context and September query features. Verify class
columns, finite normalized probabilities, memory and latency; do not select on smoke
accuracy. Project remaining work from the smoke timing. Stop with an explicit partial
status if the pilot exceeds 1800 projected seconds or less than 3GB system RAM remains.
Do not silently shorten the cohort, context budgets, or timestamps. Full-fleet runtime is
also projected and reported to inform the next study.

Evaluate both context budgets on the same September validation cohort. Choose the highest
validation average precision, breaking ties toward the smaller context. Freeze its state
and select the conservative Phase 1-style threshold for at most 1% validation alert rows.
Then score the October–December cohort once with that selected context. Do not use test
metrics to revisit any choice. LightGBM uses its frozen Phase 1 threshold, never a new
subset-specific threshold. Its cached predictions must match exact query keys and labels.

## Metrics and interpretation

Reuse Phase 1 average precision, ROC-AUC, Brier/log loss, reliability bins/ECE, alert-row
precision/recall, alert exposure and cooldown definitions. Add F1 and a [negative,positive]
confusion matrix. Report raw and selected-policy results as appropriate. Test subset
metrics are compared only against LightGBM on identical subset rows, not Phase 1's full-test
numbers. Also report monthly metrics at the frozen policy as descriptive temporal shift.

Operational event/lead-time metrics require complete expected 3-hour opportunities in each
failure's preceding 24-hour window. Filter event eligibility independently of predictions,
report retained versus excluded events, and apply the same rule to both models. Keep row
labels unchanged. Cohort event recall is never extrapolated to all 100 machines. Sparse
arbitrary timestamp samples would disable these operational metrics entirely.

Record checkpoint download separately from cold local load; context selection and tensor
construction separately; synchronized GPU forward timing (including documented SDK
pre/postprocessing if inseparable), total batch/pipeline time, p50/p95, throughput, RSS/OS
peak working set, and peak CUDA allocated/reserved bytes. Compare saved LightGBM inference
on identical feature batches and disclose device differences. No claim of equivalent training
procedures or isolated hardware fairness. Precomputed feature construction is outside scope.

Save preregistration, context/query membership, source/checkpoint digests, configuration,
model identity, predictions, selected policy, metrics and runtime evidence under Phase 2
paths. Preserve failures and negative findings. No time-series, graph, chatbot or UI work.
