# Phase 2 model-selection audit

Audit date: 2026-11-08. Exact package metadata and checkpoint API responses are retained
locally under `artifacts/phase2/research`. Downloaded checkpoints are excluded from Git.

## Selected implementation: NVIDIA Kumo Tabular small

The [official SDK](https://github.com/NVIDIA/structured-data-models) publishes
`structured-data-models==0.2.1`; its [package definition](https://github.com/NVIDIA/structured-data-models/blob/main/pyproject.toml)
requires Python >=3.11 and PyTorch >=2.7. The SDK code is Apache-2.0. It exposes
`sdm.models.KumoTabular(task="classification", size="small")`, `TableTensor` inputs and
cached `fit`/`predict`. The fit stage builds in-context inference state; it does not train
task-specific neural parameters. Context labels and query features are separate inputs.

The [official weights repository](https://huggingface.co/nvidia/Kumo-Tabular) is public.
Pinned revision: `3c3e10bbdb590ace29e7026847f92db3c603096d` (v1.0.1).
Selected file: `small/classifier.pt`, **109,936,978 bytes**. Its observed SHA-256 matches
the official LFS metadata:

```text
1ff91f484e19021aaf7d9eff6cc07e6d95a60b4aaad473e83e2ab2c3bfd2b617
```

Weights use [OpenMDW-1.1](https://huggingface.co/nvidia/Kumo-Tabular/blob/v1.0.1/LICENSE),
separate from the SDK's code license. The inspected agreement permits broad use without a
research-only or non-commercial limitation, subject to its terms, including retaining
the agreement/origin notices when distributing model materials. The checkpoint directory
retains the actual license. This does not resolve rights in downstream datasets or permit
claiming vendor endorsement. No weights are redistributed in this repository.

Small is preferred over medium/large for this laptop: classifier sizes are approximately
110MB, 246MB and 855MB respectively. The entire multi-task weights repository is much larger
than the one classifier needed here. Download bytes are not total RAM/VRAM requirements.
The pinned small checkpoint is loaded strictly into the official SDK architecture using
PyTorch's `weights_only=True`; architecture mismatches are fatal. This mirrors the upstream
loader while allowing immutable local files and avoiding implicit network/tag resolution.

CPU and CUDA paths appear in the [official usage example](https://huggingface.co/nvidia/Kumo-Tabular).
The SDK does not provide a sufficiently explicit native-Windows guarantee in the inspected
README. Therefore native Windows, CUDA operation, and CPU operation must be established by
the executable smoke evidence, rather than inferred from Python package metadata. SDK
preprocessing handles numeric/categorical inputs and missing values; this adapter preserves
the Phase 1 model-code vocabulary and passes every other accepted feature numerically.

Context/ensemble/query sizes drive runtime and cache memory. No universal safe context
limit for this hardware is assumed. Register 512/2048 context rows, one estimator, cached
inference and 64-row query batches, then measure actual memory and extrapolate runtime.
This is a smaller model/configuration than vendor headline evaluations.

## Alternative: TabICLv2

The [official implementation](https://github.com/soda-inria/tabicl) publishes `tabicl==2.2.0`.
Its package metadata requires Python >=3.10 and PyTorch >=2.2. The classification code
uses BSD-3-Clause; the [official weights card](https://huggingface.co/jingang/TabICL) also
identifies BSD-3-Clause. Preserve applicable notices and non-endorsement conditions for
redistribution. No research-only restriction is stated on the inspected classifier card.
Forecast-specific third-party code has separate notices and is outside this milestone.

Actual checkpoint identity is `jingang/TabICL`, file
`tabicl-classifier-v2-20260212.ckpt`, **110,368,038 bytes**, repository revision
`4dcd344ece2c00be9e831fdd35bed57b5ad83e19` at audit. A guessed repository named
`soda-inria/tabicl-classifier-v2-20260212` is not the official checkpoint location; it was
not used. The official classifier supports `fit`, `predict_proba`, explicit device,
checkpoint paths, ensemble size, and optional KV caching.

CPU/CUDA and Windows are represented in upstream runtime/package configuration, but this
project has not executed TabICLv2 and does not claim tested compatibility or memory needs.
Its published context scalability is not a laptop memory guarantee. It remains the fallback
if the preferred NVIDIA implementation fails its executable gates; no silent substitution
is allowed. Kumo is selected first under the user's preference, not because TabICLv2 was
found inferior or benchmarked here.

## Optional future: SAP-RPT-1.6

SAP's [official client documentation](https://sap.github.io/ai-sdk/docs/js/tabular-ai/rpt)
documents hosted RPT usage. No SAP AI Core credentials or service agreement were supplied.
This candidate is deferred without installation, API calls or claims about downloadable
1.6 weights. Do not conflate hosted 1.6 access with `SAP/sap-rpt-1-oss`.

## Hardware and isolation

Detected: Windows 11; CPython 3.12.10; 16 logical CPUs; 34,048,847,872 bytes system RAM;
approximately 11GB available at inspection; RTX 3050 6GB Laptop GPU, 6,144MiB reported by
`nvidia-smi`, driver 610.78; approximately 44GB free disk. WMI's 32-bit AdapterRAM field
underreported GPU memory, so the NVIDIA driver query is the VRAM source.

PyTorch `2.9.1+cu128` is installed in `.venv-phase2`, separately from the accepted CPU
environment. The [official PyTorch installation guidance](https://pytorch.org/get-started/locally/)
supports Windows pip/CUDA installation; usable CUDA still requires a runtime check.
Phase 1's dependencies, checkpoints, predictions, configuration, labels and reported metrics
are preserved. Final executable compatibility and resource observations belong to
`PHASE2_REPORT.md` and its smoke artifacts.
