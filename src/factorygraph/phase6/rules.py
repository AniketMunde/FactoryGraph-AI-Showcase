"""Fixed, conservative human-review rules and deterministic text templates."""

from factorygraph.phase6.common import RULE_VERSION
from factorygraph.phase6.schema import Recommendation

TEMPLATES = {
    "R001": "Prioritize human assessment of this recorded model-policy alert.",
    "R002": "Review the existing alert and its context; cooldown suppressed a new alert.",
    "R003": "Consider reviewing the visible recorded error events for this machine.",
    "R004": "Consider inspecting the visible recorded maintenance history for this machine.",
    "R005": "Consider reviewing the visible previously recorded failures for this machine.",
    "R006": "Consider comparing the recent sensor statistics with the recorded historical context.",
    "R007": "Request source-data verification; abstain from unsupported specific actions.",
}
TRIGGERS = {
    "R001": "Verified frozen policy emitted a new test-split episode",
    "R002": "Verified threshold crossing suppressed by the original 24h cooldown",
    "R003": "Verified error source facts visible in the historical window",
    "R004": "Verified maintenance source facts visible in the historical window",
    "R005": "Verified prior failure source facts visible in the historical window",
    "R006": "Verified exact-key accepted historical predictor inputs available",
    "R007": "One or more prediction, graph evidence or temporal components unavailable/incomplete",
}


class RecommendationFormatter:
    @staticmethod
    def make(rule, ids, cutoff):
        return Recommendation(
            rule_id=rule,
            rule_version=RULE_VERSION,
            trigger=TRIGGERS[rule],
            supporting_evidence_ids=ids,
            basis="model_based"
            if rule in {"R001", "R002"}
            else "general_procedural"
            if rule == "R007"
            else "source_backed",
            cutoff_exclusive=cutoff,
            action_type="data_verification" if rule == "R007" else "human_review",
            text=TEMPLATES[rule],
            limitations=(
                "Human review required; synthetic retrospective evidence does not "
                "establish a diagnosis, cause, repair or exact failure time."
            ),
        )


class DecisionRuleEngine:
    def __init__(self, config):
        self.config = config.check()

    def apply(self, prediction, policy, evidence, temporal, availability_id, cutoff):
        result = []

        def add(rule, ids):
            result.append(RecommendationFormatter.make(rule, ids, cutoff))

        if prediction.status == "verified" and policy.status == "verified":
            ids = [prediction.record_id, policy.record_id]
            if policy.new_alert:
                add("R001", ids)
            elif policy.cooldown_suppressed:
                add("R002", ids)
        if evidence["status"] == "verified":
            for kind, rule in [("errors", "R003"), ("maint", "R004"), ("failures", "R005")]:
                ids = [r["id"] for r in evidence["facts"] if r["kind"] == kind]
                if ids:
                    add(rule, ids)
        if "approved_predictor_inputs" in temporal:
            add("R006", [temporal["approved_predictor_inputs"]["record_id"]])
        if (
            prediction.status != "verified"
            or evidence["status"] != "verified"
            or temporal["status"] != "verified"
        ):
            add("R007", [availability_id])
        return result

    def validate(
        self, recommendations, prediction, policy, evidence, temporal, availability_id, cutoff
    ):
        expected = self.apply(prediction, policy, evidence, temporal, availability_id, cutoff)
        if [r.model_dump() for r in recommendations] != [r.model_dump() for r in expected]:
            raise ValueError("Recommendation grounding/template mismatch")


def explanation(prediction, policy, evidence, temporal, recommendations):
    if prediction.status == "verified":
        model = (
            "Retrospective model estimate: calibrated probability "
            f"{prediction.probability:.8f} for failure within 24 hours."
        )
    else:
        model = "Primary risk unavailable: no verified approved prediction for this request."
    if policy.status != "verified":
        decision = "Frozen alert policy cannot be evaluated for this request."
    elif policy.new_alert:
        decision = "The frozen policy generated a new alert episode; human assessment is suggested."
    elif policy.cooldown_suppressed:
        decision = "The score crosses the frozen threshold, but cooldown suppressed another alert."
    else:
        decision = (
            "The score is below the frozen threshold; this is no assurance of safe operation."
        )
    history = (
        f"Recorded history: {len(evidence['facts'])} source records shown in the bounded window."
        if evidence["status"] == "verified"
        else "Recorded history unavailable; database or validation failure is not an empty history."
    )
    context = (
        "Historical sensor inputs and supplementary forecast context are separately identified."
        if temporal["status"] in {"verified", "incomplete"}
        else "Historical sensor/forecast context unavailable for this exact request."
    )
    return [
        model,
        decision,
        history,
        context,
        *[r.text for r in recommendations],
        (
            "Historical associations and model outputs do not establish machinery"
            " failure or root cause."
        ),
    ]
