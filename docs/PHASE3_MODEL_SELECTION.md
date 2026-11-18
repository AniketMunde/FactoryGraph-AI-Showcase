# Phase 3 model feasibility audit — 2026-11-12

Selected **Amazon Chronos-2**, official [implementation](https://github.com/amazon-science/chronos-forecasting)
and [model card](https://huggingface.co/amazon/chronos-2). No task-specific neural training,
LoRA or substitute model is used. Native Windows CPU and CUDA execution passed genuine
smoke inference; exact repeat difference was zero on the measured GPU batch.

Checkpoint revision `29ec3766d36d6f73f0696f85560a422f50e8498c`; `model.safetensors`,
477,930,472 bytes, SHA-256
`ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42`.
The 119,477,664-parameter model loads through official
`Chronos2Pipeline.from_pretrained(local_path, local_files_only=True)` after digest checks.
Only safetensors, config and model card are downloaded; no remote-code trust or optimizer
checkpoint is needed. The package's Apache notice is retained alongside the checkpoint.

Code and weights are identified as Apache-2.0 by the official repository/model card.
This permits research and commercial use subject to the license's notice/redistribution
conditions; model suitability and dataset rights are separate. The HF repository has no
separate weight-license file, so the manifest explicitly records the model-card declaration
and retained upstream package license rather than inventing a downloaded LICENSE file.

Audited package `chronos-forecasting==2.3.2` requires Python >=3.10, torch >=2.2,<3,
Transformers >=4.41,<6, pandas >=2,<4, NumPy >=1.21,<3, accelerate >=1.1,<2 and einops
>=0.7,<1. Select Python 3.12, torch 2.9.1+cu128 and Transformers 4.57.6 in `.venv-phase3`.
Transformers 4.57.6 requires Hugging Face Hub <1, conflicting with the accepted Phase 2
Hub 2.4.0 pin. Isolation is necessary; neither accepted lock/environment is changed.
The exact resolved Phase 3 dependencies are in `requirements/phase3-cu128.lock`.

`predict_quantiles` accepts `[batch, variates, history]` arrays and returns one tensor
`[variates, horizon, quantiles]` per origin. Each origin is a distinct multivariate group;
`cross_learning=False` prevents sharing information across origins. Request quantiles
0.1/0.5/0.9 and use median for point errors. No future covariates are provided.
The checkpoint config supports 8192 context steps and 1024 output steps (64 patches of16);
the registered studies use far smaller contexts/horizons. SDK batch size counts variates,
so 16 Azure origin groups correspond to 64 variate tasks, not 16 scalar series.

Chronos supports missing-value masks and variable-length histories, but this study takes a
conservative complete-context/complete-target policy with no imputation. Its internal
context normalization and quantile postprocessing stay inside the SDK; output forecasts
are in source units. Tests prove only pre-issue context reaches the model. Pretraining
corpus overlap with these public benchmarks is not ruled out: zero-shot here means no
local task-specific neural training, not a guarantee the source data were never seen.

Fresh preflight: RTX 3050 Laptop GPU, driver 610.78, 6144MiB total / 6001MiB free VRAM;
34.05GB RAM with about 12.8GB available; 38.8GB free disk. Initial Azure smoke measured
about 526MB peak CUDA allocation and 552MB reserved. A 16-origin GPU batch took 83ms;
a one-origin CPU batch took 155ms. Cold local load/import/integrity took 60.8s on its
first execution; warm-import CPU loading in the same process took 0.46s. These are
different cache/startup states and not a controlled CPU/GPU speed comparison. Smoke RSS
includes both loaded models and Python libraries. Actual full-run resources are reported
separately. Checkpoint bytes alone were not used to assert hardware suitability.

Optional Kumo Anomaly is deferred as an anomaly/reconstruction model, not a replacement
for the registered forecaster. TimesFM is also deferred; its source license must never
be treated as proof of rights for every checkpoint version. No optional model inference
or performance comparison is claimed in Phase 3.
