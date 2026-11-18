"""Stable, JSON-safe operator report contract; evaluator labels are forbidden."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from factorygraph.phase6.common import RULE_IDS, RULE_VERSION, VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Request(StrictModel):
    machine_id: int = Field(strict=True, gt=0)
    snapshot: str
    mode: Literal["retrospective_replay"] = "retrospective_replay"


class Prediction(StrictModel):
    status: Literal["verified", "unavailable"]
    reason: str | None = None
    machine_id: int | None = None
    snapshot: str | None = None
    horizon_hours: Literal[24] = 24
    probability: float | None = Field(default=None, ge=0, le=1)
    model_id: str | None = None
    model_sha256: str | None = None
    calibration_sha256: str | None = None
    prediction_file_sha256: str | None = None
    policy_sha256: str | None = None
    dataset_id: str | None = None
    split: Literal["test"] = "test"
    mode: Literal["retrospective_replay"] = "retrospective_replay"
    record_id: str | None = None

    @model_validator(mode="after")
    def complete(self):
        required = [
            self.machine_id,
            self.snapshot,
            self.probability,
            self.model_id,
            self.model_sha256,
            self.calibration_sha256,
            self.prediction_file_sha256,
            self.policy_sha256,
            self.dataset_id,
            self.record_id,
        ]
        if self.status == "verified" and any(v is None for v in required):
            raise ValueError("Verified prediction requires full identity")
        if self.status == "unavailable" and self.probability is not None:
            raise ValueError("Unverified prediction may not expose probability")
        return self


class AlertPolicy(StrictModel):
    status: Literal["verified", "unavailable"]
    threshold: float | None = None
    cooldown_hours: Literal[24] = 24
    selected_on: str = "September validation; frozen for test"
    policy_sha256: str | None = None
    record_id: str | None = None
    above_threshold: bool | None = None
    new_alert: bool | None = None
    cooldown_suppressed: bool | None = None
    last_episode_timestamp: str | None = None
    scope: str = "Accepted test split; greedy episodes restart at split boundary"


class Recommendation(StrictModel):
    rule_id: str
    rule_version: Literal["1.0.0"] = RULE_VERSION
    trigger: str
    supporting_evidence_ids: list[str]
    basis: Literal["model_based", "source_backed", "general_procedural"]
    cutoff_exclusive: str
    action_type: Literal["human_review", "data_verification"]
    text: str
    limitations: str
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def grounded(self):
        if self.rule_id not in RULE_IDS or not self.supporting_evidence_ids:
            raise ValueError("Unknown or ungrounded recommendation")
        return self


class CaseReport(StrictModel):
    schema_version: Literal["factorygraph-phase6-v1"] = VERSION
    case_id: str
    request: Request
    status: Literal["complete", "degraded", "evidence_only", "abstained"]
    prediction: Prediction
    alert_policy: AlertPolicy
    historical_evidence: dict
    temporal_context: dict
    recommendations: list[Recommendation]
    human_review_priority: Literal[
        "policy_alert_review", "existing_alert_review", "routine_review", "data_verification"
    ]
    explanation: list[str]
    data_availability: dict
    provenance: dict
    limitations: list[str]

    @model_validator(mode="after")
    def no_outcomes(self):
        forbidden = {"label", "label_end", "next_failure", "ground_truth", "future_outcome"}

        def check(value):
            if isinstance(value, dict):
                if forbidden & value.keys():
                    raise ValueError("Future evaluator fields forbidden in operator report")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)

        check(self.model_dump())
        return self
