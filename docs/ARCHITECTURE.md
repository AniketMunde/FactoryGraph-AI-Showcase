# Architecture and execution boundaries

![Offline research and online replay](media/architecture.svg)

Offline training/evaluation produces frozen accepted outputs. Online historical replay
uses the approved LightGBM/policy, saved supplementary Chronos context and historical
source-validated graph evidence. It does not perform live Kumo/Chronos inference on
a machine selection. Kumo remains an offline benchmark.

```mermaid
flowchart LR
 subgraph Offline
  D[Historical source acquisition] --> F[Causal features and chronological evaluation]
  F --> L[LightGBM calibration]
  F --> K[Kumo evaluation]
  D --> C[Chronos forecasts]
  D --> G[Historical graph]
 end
 L --> A[Approved frozen predictions and policy]
 C --> H[Saved supplementary context]
 subgraph Replay
  U[Next.js or Streamlit] --> B[Authenticated FastAPI]
  B --> E[Case report engine]
  E --> R[Evidence and deterministic human review]
 end
 A --> E
 H --> E
 G --> E
```

![Research workflow](media/research-workflow.svg)

The [interface map](media/console-overview-illustrative.svg) is illustrative; the
[media inventory](MEDIA.md) distinguishes it from actual software captures.
