# Future model feasibility register

Documentation checked **2026-11-08**. These are candidates, not installed integrations or
final selections. Recheck the exact checkpoint revision, SDK, access terms, input format,
task support and hardware limits immediately before implementation. Vendor benchmark claims
are not FactoryGraph results. Never assume a source-code license also covers weights.

| Candidate | Verified official information | Remaining selection gate |
|---|---|---|
| NVIDIA Kumo Tabular / Forecast / Anomaly | NVIDIA documents these families and Python versus NIM/client execution routes. Tabular consumes labeled context and numerical/categorical tables; raw timestamps need preprocessing. [Overview](https://docs.nvidia.com/sdgm/about-nvidia-kumo/overview), [selection guide](https://docs.nvidia.com/sdgm/client/faq/kumo-foundation-models/which-foundation-model-should-i-choose) | Exact checkpoint and downloadable access, weights license, SDK/version compatibility, memory/context limits and local CPU feasibility remain unaudited. No claim of universal public download access |
| SAP/sap-rpt-1-oss | Official card documents DataFrame/NumPy inputs and sklearn-style classifier/regressor APIs. Download requires HF login/conditions; Apache source notice includes inherited research-use restrictions. Card recommends 80GB GPU for its high-context best-performance setting and lower context/bagging for reduced demand. [Model card](https://huggingface.co/SAP/sap-rpt-1-oss) | Distinguish OSS checkpoint from hosted commercial RPT variants. Measure complete embedding/model footprint and validate licensing restrictions before selection; do not assume a small checkpoint implies a lightweight full pipeline |
| Amazon Chronos-2 | Public `amazon/chronos-2` card lists Apache-2.0, 120M parameters and CPU/GPU inference. Official `Chronos2Pipeline.from_pretrained` / `predict_df` accept keyed timestamped targets and optional covariates; quantile forecasts are available. [Model card](https://huggingface.co/amazon/chronos-2), [SDK](https://github.com/amazon-science/chronos-forecasting) | Pin SDK and weights, audit context limits and training-data overlap, measure RAM/latency on this host. Future covariates are permissible only if known at prediction time |
| Google TimesFM | Official README distinguishes Apache source and weights through 2.5 from separately licensed, non-commercial/non-production 3.0 weights. Version 3 examples use `TimesFM3Evaluator` and array histories; APIs differ by version. [Official repository](https://github.com/google-research/timesfm#license-notice-for-pretrained-weights) | Select version deliberately; verify complete weight terms, local CPU support, numerical behavior, dependencies and measured resources. Do not infer 3.0 deployment rights from the code license |

No choice has yet passed all gates. Phase 2 should first audit one tabular candidate on the
available hardware and document either a working adapter or a concrete access/resource blocker.
Keep foundation-model dependencies in separate optional environments until compatibility is
demonstrated. Define adapters around stable project-owned feature and prediction contracts,
not a single vendor SDK. Do not fabricate outputs to complete an ablation matrix.
