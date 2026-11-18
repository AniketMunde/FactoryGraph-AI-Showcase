"use client";
import { Download, ExternalLink, FileCheck2, ShieldCheck } from "lucide-react";
import type { CaseReport } from "@/lib/contracts";
import { countKind, percent, policy, readable, utc } from "@/lib/presentation";
import { Badge, Button, Empty, KeyValues, Panel } from "./ui";
export function Export({ report }: { report: CaseReport }) {
  function download() {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `factorygraph-machine-${report.request.machine_id}-${report.request.snapshot.slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Button variant="primary" onClick={download}>
      <Download size={15} />
      Export verified JSON
    </Button>
  );
}
export function RiskSummary({ report }: { report: CaseReport }) {
  const state = policy(report);
  const p = report.prediction.probability;
  return (
    <Panel className="risk-panel">
      <div className="risk-top">
        <div>
          <p className="eyebrow">Approved calibrated estimate · next 24 hours</p>
          <div className="risk-number" data-testid="risk-probability" title={String(p)}>
            {percent(p, 6)}
          </div>
          <p className="muted">
            {report.prediction.model_id ?? "No approved prediction at this cutoff"}
          </p>
        </div>
        <Badge tone={state.tone}>{state.label}</Badge>
      </div>
      <div className="risk-policy">
        <div>
          <span>Frozen threshold</span>
          <strong className="mono" data-testid="threshold">
            {report.alert_policy.threshold ?? "Unavailable"}
          </strong>
        </div>
        <div>
          <span>Original cooldown</span>
          <strong>{report.alert_policy.cooldown_hours} hours</strong>
        </div>
        <div>
          <span>Policy interpretation</span>
          <strong>
            {report.alert_policy.new_alert
              ? "Human review suggested"
              : report.alert_policy.cooldown_suppressed
                ? "Alert suppressed by existing cooldown"
                : report.prediction.status !== "verified"
                  ? "Evidence only · no borrowed score"
                  : "Below threshold · no safety guarantee"}
          </strong>
        </div>
      </div>
    </Panel>
  );
}
export function Recommendations({
  report,
  onEvidence,
}: {
  report: CaseReport;
  onEvidence: (id: string) => void;
}) {
  return (
    <Panel
      title="Human-review suggestions"
      eyebrow="DETERMINISTIC RULES · NO AUTONOMOUS ACTION"
      action={<ShieldCheck size={18} />}
    >
      <div className="recommendations">
        {!report.recommendations.length ? (
          <Empty title="No recommendation available">
            The accepted report has no applicable recommendation at this cutoff.
          </Empty>
        ) : (
          report.recommendations.map((rule) => (
            <article className="recommendation" key={rule.rule_id}>
              <div className="rule-id">{rule.rule_id}</div>
              <div>
                <div className="rule-top">
                  <strong>{rule.text}</strong>
                  <span className="basis">{readable(rule.basis)}</span>
                </div>
                <p>{rule.limitations}</p>
                <div className="support-links">
                  {rule.supporting_evidence_ids.slice(0, 4).map((id, index) => (
                    <button key={id} onClick={() => onEvidence(id)}>
                      Evidence {index + 1}
                      <ExternalLink size={11} />
                    </button>
                  ))}
                  {rule.supporting_evidence_ids.length > 4 && (
                    <span>
                      {rule.supporting_evidence_ids.length - 4} more IDs retained in verified export
                    </span>
                  )}
                </div>
                <small>
                  Rule {rule.rule_version} · cutoff {utc(rule.cutoff_exclusive, true)}
                </small>
              </div>
            </article>
          ))
        )}
      </div>
    </Panel>
  );
}
export function EvidenceSummary({
  report,
  onEvidence,
}: {
  report: CaseReport;
  onEvidence: (id: string) => void;
}) {
  if (report.historical_evidence.status !== "verified")
    return (
      <Panel title="Historical evidence unavailable">
        <Empty title="No verified source history is available">
          {readable(report.historical_evidence.reason)}. This is not a verified empty history.
        </Empty>
      </Panel>
    );
  const kinds = [
    { key: "errors", name: "Error records" },
    { key: "maint", name: "Maintenance records" },
    { key: "failures", name: "Prior failure records" },
  ];
  return (
    <Panel
      title="Source-backed historical evidence"
      eyebrow="RECORDED FACTS · STRICTLY BEFORE CUTOFF"
      action={
        <Badge tone={report.historical_evidence.status === "verified" ? "verified" : "muted"}>
          {report.historical_evidence.status}
        </Badge>
      }
    >
      <div className="evidence-counts">
        {kinds.map((kind) => (
          <div key={kind.key}>
            <strong>
              {report.historical_evidence.status === "verified" ? countKind(report, kind.key) : "—"}
            </strong>
            <span>{kind.name}</span>
          </div>
        ))}
      </div>
      <div className="evidence-rows">
        {(report.historical_evidence.facts ?? [])
          .slice(-4)
          .reverse()
          .map((fact) => (
            <button key={fact.id} onClick={() => onEvidence(fact.id)}>
              <span className={`event-dot event-${fact.kind}`} />
              <strong>{fact.code}</strong>
              <span>{fact.source_table}</span>
              <time>{utc(fact.event_timestamp, true)}</time>
              <ExternalLink size={13} />
            </button>
          ))}
      </div>
      <p className="panel-note">
        {report.historical_evidence.pagination?.truncated
          ? "Bounded evidence is truncated; consult the report pagination fields."
          : "Counts above describe returned source records in the bounded historical window."}{" "}
        Overlapping maintenance/failure records retain their original meaning.
      </p>
    </Panel>
  );
}
export function Context({ report }: { report: CaseReport }) {
  const temporal = report.temporal_context;
  const context = temporal.supplementary_chronos_context;
  return (
    <Panel title="Supplementary Chronos context" eyebrow="SEPARATE FROM THE APPROVED PREDICTOR">
      <div className="panel-body">
        <div className="callout">
          Forecast summaries and matured historical residuals are supplementary. They do not change
          the A0 probability or identify a physical diagnosis.
        </div>
        {temporal.status !== "verified" || !context ? (
          <Empty title="Supplementary context unavailable">{readable(temporal.reason)}</Empty>
        ) : (
          <>
            <KeyValues
              values={{
                model: context.model_id,
                revision: context.checkpoint_revision,
                forecast_issue_UTC: context.forecast_issue_timestamp,
                latest_residual_observation_UTC: context.latest_residual_observation_timestamp,
                modifies_primary_probability: context.modifies_primary_probability,
              }}
            />
            <div className="table-scroll">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>Historical feature</th>
                    <th>Accepted value</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(context.values ?? {}).map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono">{k}</td>
                      <td className="tabular">{v === null ? "Unknown" : v.toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
export function Provenance({ report }: { report: CaseReport }) {
  return (
    <Panel
      title="Provenance and audit details"
      eyebrow="VERIFIED REPORT IDENTITY"
      action={<FileCheck2 size={18} />}
    >
      <div className="panel-body">
        <KeyValues
          values={{
            case_id: report.case_id,
            schema: report.schema_version,
            model_id: report.prediction.model_id,
            model_sha256: report.prediction.model_sha256,
            calibration_sha256: report.prediction.calibration_sha256,
            policy_sha256: report.prediction.policy_sha256,
            graph: report.provenance.graph,
            dataset: report.provenance.dataset_identity,
            availability_policy: report.provenance.availability_policy,
            artifact_trust: report.provenance.artifact_trust,
          }}
        />
      </div>
    </Panel>
  );
}
export function FullReport({
  report,
  onEvidence,
}: {
  report: CaseReport;
  onEvidence: (id: string) => void;
}) {
  return (
    <div className="report-stack">
      <div className="section-intro">
        <div>
          <p className="eyebrow">Verified case report</p>
          <h2>
            Machine {report.request.machine_id} · {utc(report.request.snapshot)}
          </h2>
        </div>
        <Export report={report} />
      </div>
      <RiskSummary report={report} />
      <Panel title="Prediction and scope">
        <div className="panel-body">
          {report.explanation.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      </Panel>
      <EvidenceSummary report={report} onEvidence={onEvidence} />
      <Panel title="Sensor and temporal context">
        <div className="panel-body">
          <KeyValues
            values={{
              primary_inputs: report.temporal_context.approved_predictor_inputs?.record_id,
              latest_source_observation:
                report.temporal_context.approved_predictor_inputs
                  ?.latest_source_observation_timestamp,
              supplementary_context: report.temporal_context.status,
              interpretation:
                "Measured source features and supplementary forecasts are separate from model-based statements.",
            }}
          />
        </div>
      </Panel>
      <Recommendations report={report} onEvidence={onEvidence} />
      <Panel title="Limitations">
        <ul className="limitations">
          {report.limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </Panel>
      <Provenance report={report} />
    </div>
  );
}
