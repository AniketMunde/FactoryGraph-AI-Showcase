# Phase 6 recommendation rules v1 — registered 2026-11-14

Rules version 1.0.0 has the exact allowlist in configs/phase6/rules-v1.json. Unknown
versions/IDs/configuration keys fail closed. No probability band is fitted or introduced.
Templates are fixed code, and no source/user text is executed as an instruction.

| ID | Trigger | Human-review suggestion | Support |
|---|---|---|---|
| R001 | verified primary policy emits a new episode | Prioritize human assessment of the recorded alert | model/policy IDs |
| R002 | verified score crosses threshold but cooldown suppresses episode | Review the existing alert and its context; this is no new alert | model/policy IDs and last episode |
| R003 | verified visible own-window errors | Review these recorded error events | visible source fact IDs |
| R004 | verified visible own-window maintenance | Inspect this recorded maintenance history | visible source fact IDs |
| R005 | verified visible own-window failures | Review these previously recorded failures | visible source fact IDs |
| R006 | verified exact-key historical predictor inputs | Compare recent sensor statistics with recorded historical context | feature artifact/row ID |
| R007 | any required prediction/evidence/context unavailable | Request source-data verification; abstain from unsupported specifics | availability record (general procedural guidance) |

Each output contains rule/version, triggering condition, supporting IDs, model/source/
procedural status, cutoff, action type, limitations and human_review_required=true.
When the primary prediction is unverified, neither R001 nor R002 may fire. When graph
evidence is invalid/unavailable, R003–R005 may not fire. R006 does not diagnose a cause.
Below-threshold cases are routine human review, never an invented safe-operation guarantee.
The template inventory cannot assert component failure, causation, mandatory replacement,
an exact future failure time, or proof of root cause. No attribution is implemented.
