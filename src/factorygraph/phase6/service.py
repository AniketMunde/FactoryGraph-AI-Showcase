"""Reusable offline service with deterministic content and separate measured costs."""

import time

from factorygraph.phase4.config import timestamp
from factorygraph.phase4.queries import machine_id
from factorygraph.phase6.common import digest, iso
from factorygraph.phase6.evidence import HistoricalEvidenceRetriever, SourceCatalog
from factorygraph.phase6.integrity import ArtifactRegistry
from factorygraph.phase6.prediction import PolicyEvaluator, PredictionReader
from factorygraph.phase6.rules import DecisionRuleEngine, explanation
from factorygraph.phase6.schema import CaseReport, Request
from factorygraph.phase6.temporal import TemporalContextReader

LIMITATIONS = [
    "Historical synthetic Azure replay; not live predictive maintenance or field validation.",
    (
        "UTC, static metadata availability and immediate source event "
        "availability are assumptions; source arrival timestamps are not "
        "measured."
    ),
    (
        "Recorded component codes are categories; model peers are metadata "
        "associations, not physical dependencies."
    ),
    (
        "The approved baseline is retained after the Phase 5 NO-GO; "
        "supplementary Chronos context does not change its probability."
    ),
    (
        "Probabilities, source records, derived statistics and review "
        "suggestions are distinct; none establishes a diagnosis or cause."
    ),
    (
        "No repairs, shutdowns, costs, exact failure times or autonomous "
        "actions are prescribed. Human review is required."
    ),
    (
        "MetroPT-3 real-data testing remains incomplete; prospective decision"
        " utility has not been evaluated."
    ),
]


class ProvenanceRecorder:
    def __init__(self, registry, evidence):
        self.registry = registry
        self.evidence = evidence

    def record(self, prediction, policy, evidence, temporal, recommendations, availability_id):
        facts = []
        aggregates = []
        if evidence["status"] == "verified":
            facts = sorted(
                {r["id"] for r in evidence["facts"]}
                | set(evidence["derived_aggregates"]["supporting_source_fact_ids"])
            )
            aggregates = [
                evidence["derived_aggregates"]["record_id"],
                evidence["machine"]["record_id"],
            ]
        return {
            "case_configuration_sha256": self.registry.config.digest(),
            "registration_sha256": digest(self.registry.record),
            "frozen_input_manifest_sha256": digest(self.registry.hashes),
            "model_sha256": prediction.model_sha256,
            "calibration_sha256": prediction.calibration_sha256,
            "policy_sha256": policy.policy_sha256,
            "prediction_file_sha256": prediction.prediction_file_sha256,
            "graph": {
                **self.evidence.identity,
                "verified_for_case": evidence["status"] == "verified",
            },
            "source_fact_ids": facts,
            "aggregate_and_metadata_ids": aggregates,
            "temporal_artifact_sha256": temporal.get("supplementary_chronos_context", {}).get(
                "artifact_sha256"
            ),
            "recommendation_rule_ids": [r.rule_id for r in recommendations],
            "availability_record_id": availability_id,
            "dataset_identity": (
                "Microsoft Azure Predictive Maintenance synthetic; pinned source file"
                " hashes in registration"
            ),
            "availability_policy": (
                "source event time < snapshot; forecast issue <= snapshot; residual "
                "observation < snapshot"
            ),
            "artifact_trust": (
                "Frozen local file digests; drift detection, not a signed supply-chain guarantee"
            ),
        }


class CaseReportBuilder:
    def __init__(self, config, database=None):
        started = time.perf_counter()
        self.registry = ArtifactRegistry(config)
        self.config = config
        self.predictions = PredictionReader(self.registry)
        self.policy = PolicyEvaluator(self.predictions)
        self.catalog = SourceCatalog(self.registry)
        self.evidence = HistoricalEvidenceRetriever(self.registry, self.catalog, database)
        self.temporal = TemporalContextReader(self.registry)
        self.rules = DecisionRuleEngine(config)
        self.provenance = ProvenanceRecorder(self.registry, self.evidence)
        self.initialization_seconds = time.perf_counter() - started
        self.last_timing = {}

    def build(self, machine, snapshot):
        started = time.perf_counter()
        machine = machine_id(machine)
        cutoff = timestamp(snapshot)
        request = Request(machine_id=machine, snapshot=iso(cutoff))
        known = not self.catalog.error and machine in self.catalog.machines.index
        prediction = self.predictions.get(machine, cutoff)
        policy = self.policy.get(prediction)
        tick = time.perf_counter()
        evidence = (
            self.evidence.get(machine, cutoff)
            if known
            else {
                "status": "unavailable",
                "reason": self.catalog.error or "unknown_machine",
                "fallback": "disabled",
            }
        )
        graph_seconds = time.perf_counter() - tick
        tick = time.perf_counter()
        temporal = (
            self.temporal.get(machine, cutoff)
            if known
            else {"status": "unavailable", "reason": self.catalog.error or "unknown_machine"}
        )
        context_seconds = time.perf_counter() - tick
        availability = {
            "prediction": {"status": prediction.status, "reason": prediction.reason},
            "graph_evidence": {"status": evidence["status"], "reason": evidence.get("reason")},
            "temporal_context": {"status": temporal["status"], "reason": temporal.get("reason")},
        }
        availability_id = "availability:" + digest([request.model_dump(), availability])
        recommendations = self.rules.apply(
            prediction, policy, evidence, temporal, availability_id, iso(cutoff)
        )
        self.rules.validate(
            recommendations, prediction, policy, evidence, temporal, availability_id, iso(cutoff)
        )
        if prediction.status == "verified":
            status = (
                "complete"
                if evidence["status"] == "verified" and temporal["status"] == "verified"
                else "degraded"
            )
        else:
            status = "evidence_only" if evidence["status"] == "verified" else "abstained"
        priority = (
            "policy_alert_review"
            if policy.new_alert
            else "existing_alert_review"
            if policy.cooldown_suppressed
            else "routine_review"
            if status == "complete"
            else "data_verification"
        )
        report = CaseReport(
            case_id="case:"
            + digest([request.model_dump(), self.config.digest(), digest(self.registry.record)]),
            request=request,
            status=status,
            prediction=prediction,
            alert_policy=policy,
            historical_evidence=evidence,
            temporal_context=temporal,
            recommendations=recommendations,
            human_review_priority=priority,
            explanation=explanation(prediction, policy, evidence, temporal, recommendations),
            data_availability={"record_id": availability_id, **availability},
            provenance=self.provenance.record(
                prediction, policy, evidence, temporal, recommendations, availability_id
            ),
            limitations=LIMITATIONS,
        )
        result = report.model_dump(mode="json")
        self.last_timing = {
            "graph_retrieval_and_validation_seconds": graph_seconds,
            "temporal_context_seconds": context_seconds,
            "case_total_seconds": time.perf_counter() - started,
            "neo4j_queries_seconds": self.evidence.last_timing.get("neo4j_queries_seconds", 0.0)
            if known
            else 0.0,
            "source_validation_seconds": self.evidence.last_timing.get(
                "source_validation_seconds", 0.0
            )
            if known
            else 0.0,
        }
        return result

    def fleet(self, snapshot, machines=None):
        cutoff = timestamp(snapshot)
        if self.predictions.error:
            raise ValueError("Approved fleet predictions unavailable")
        supported = sorted(
            int(m)
            for m in self.predictions.frame.loc[
                self.predictions.frame.datetime == cutoff, "machineID"
            ]
        )
        selected = supported if machines is None else sorted(machines)
        if (
            not selected
            or len(selected) > self.config.fleet_limit
            or len(set(selected)) != len(selected)
            or not set(selected).issubset(supported)
        ):
            raise ValueError("Fleet requires bounded unique accepted exact test identities")
        return [self.build(machine, cutoff) for machine in selected]

    def close(self):
        self.evidence.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
