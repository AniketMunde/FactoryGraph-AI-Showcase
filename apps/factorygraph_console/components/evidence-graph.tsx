"use client";
import { Box, Database, Factory, GitBranch, Network, ScanSearch, Users } from "lucide-react";
import type { CaseReport } from "@/lib/contracts";
import { Drawer, Empty, KeyValues, Panel } from "./ui";
import { utc } from "@/lib/presentation";
type Node = { id: string; label: string; detail: string; x: number; y: number; kind: string };
export function EvidenceGraph({
  report,
  onEvidence,
}: {
  report: CaseReport;
  onEvidence: (id: string) => void;
}) {
  const evidence = report.historical_evidence;
  if (evidence.status !== "verified")
    return (
      <Empty title="Verified graph evidence unavailable">
        No empty valid graph or physical relationship is inferred.
      </Empty>
    );
  const events = [...(evidence.facts ?? [])]
    .sort((a, b) => Date.parse(b.event_timestamp) - Date.parse(a.event_timestamp))
    .slice(0, 8);
  const peers = evidence.derived_aggregates?.model_peers?.slice(0, 3) ?? [];
  const nodes: Node[] = [
    {
      id: evidence.machine?.record_id ?? "machine",
      label: `Machine ${report.request.machine_id}`,
      detail: "Recorded asset identity",
      x: 250,
      y: 270,
      kind: "machine",
    },
    {
      id: "projection:model",
      label: evidence.machine?.model ?? "Model unavailable",
      detail: "Recorded model category",
      x: 500,
      y: 60,
      kind: "model",
    },
    ...events.map((event, i) => ({
      id: event.id,
      label: event.code,
      detail: utc(event.event_timestamp, true),
      x: 675,
      y: 115 + i * 55,
      kind: event.kind,
    })),
    ...peers.map((peer, i) => ({
      id: `projection:peer:${peer.machine_id}`,
      label: `Machine ${peer.machine_id}`,
      detail: "Same model · derived",
      x: 85,
      y: 125 + i * 135,
      kind: "peer",
    })),
  ];
  const categories = [...new Set(events.map((event) => event.code))];
  categories.slice(0, 6).forEach((code, i) =>
    nodes.push({
      id: `projection:category:${code}`,
      label: code,
      detail: "Recorded event category",
      x: 925,
      y: 140 + i * 74,
      kind: "category",
    }),
  );
  const links = nodes
    .filter((n) => n.kind !== "machine" && n.kind !== "category")
    .map((n) => ({ from: nodes[0], to: n, derived: n.kind === "peer" }));
  events.forEach((event) => {
    const category = nodes.find((n) => n.id === `projection:category:${event.code}`);
    if (category)
      links.push({ from: nodes.find((n) => n.id === event.id)!, to: category, derived: true });
  });
  return (
    <Panel
      title="Historical relationship view"
      eyebrow="BOUNDED SOURCE PROJECTION · NOT PHYSICAL CONNECTIVITY"
      action={<span className="muted small">{nodes.length} nodes</span>}
    >
      <div className="graph-legend">
        <span>
          <i className="line-recorded" />
          Recorded metadata / event link
        </span>
        <span>
          <i className="line-derived" />
          Derived category / peer association
        </span>
        <span>Cutoff {utc(report.request.snapshot, true)}</span>
      </div>
      <div className="graph-scroll">
        <div className="graph-canvas" role="group" aria-label="Source-grounded historical graph">
          <svg viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true">
            {links.map((edge, i) => (
              <path
                key={i}
                d={`M ${edge.from.x} ${edge.from.y} C ${(edge.from.x + edge.to.x) / 2} ${edge.from.y}, ${(edge.from.x + edge.to.x) / 2} ${edge.to.y}, ${edge.to.x} ${edge.to.y}`}
                fill="none"
                stroke={edge.derived ? "#b18741" : "#b6c7d8"}
                strokeWidth="1.5"
                strokeDasharray={edge.derived ? "5 5" : undefined}
              />
            ))}
          </svg>
          {nodes.map((node) => {
            const Icon =
              node.kind === "machine"
                ? Factory
                : node.kind === "model"
                  ? Box
                  : node.kind === "peer"
                    ? Users
                    : node.kind === "category"
                      ? GitBranch
                      : Database;
            return (
              <button
                key={node.id}
                className={`graph-node node-${node.kind}`}
                style={{ left: `${node.x / 10}%`, top: `${node.y / 6}%` }}
                onClick={() => onEvidence(node.id)}
                aria-label={`Inspect ${node.label} ${node.detail}`}
              >
                <Icon size={16} />
                <strong>{node.label}</strong>
                <small>{node.detail}</small>
              </button>
            );
          })}
        </div>
      </div>
      <footer className="panel-note">
        <Network size={14} />
        The latest {events.length} returned events and {peers.length} permitted model peers are
        shown. Category nodes are derived display groupings, not component instances or causal
        links.
      </footer>
    </Panel>
  );
}
export function EvidenceDrawer({
  report,
  id,
  onClose,
}: {
  report: CaseReport;
  id: string | null;
  onClose: () => void;
}) {
  const fact = report.historical_evidence.facts?.find(
    (f) => f.id === id || f.source_record_id === id,
  );
  let title = "Evidence identity",
    values: Record<string, unknown> = {
      evidence_id: id,
      visibility_cutoff: report.request.snapshot,
      note: "This supporting ID is retained by the accepted report. A complete source row is not exposed in this bounded case; no additional record is fabricated.",
    };
  if (fact) {
    title = `Recorded ${fact.code}`;
    values = {
      relationship_meaning: "Recorded historical source event for the selected machine",
      ...fact,
      visibility_cutoff_exclusive: report.historical_evidence.cutoff_exclusive,
    };
  } else if (id === report.prediction.record_id) {
    title = "Approved model prediction";
    values = {
      basis: "Model-based estimate; not a recorded failure or diagnosis",
      ...report.prediction,
    };
  } else if (id === report.alert_policy.record_id) {
    title = "Frozen policy decision";
    values = { basis: "Deterministic threshold and cooldown evaluation", ...report.alert_policy };
  } else if (id === report.historical_evidence.machine?.record_id) {
    title = `Machine ${report.request.machine_id}`;
    values = {
      ...report.historical_evidence.machine,
      relationship_meaning: "Recorded source metadata, known at study start",
    };
  } else if (id?.startsWith("projection:")) {
    title = "Derived graph projection";
    values = {
      projection_id: id,
      relationship_meaning: id.includes("peer")
        ? "Same recorded model category; not physical connectivity"
        : "Grouping of recorded model/event category in the returned case",
      visibility_cutoff: report.request.snapshot,
      source_metadata: report.historical_evidence.machine,
      definition: report.historical_evidence.derived_aggregates?.definition,
    };
  }
  return (
    <Drawer title={title} open={Boolean(id)} onClose={onClose}>
      <div className="drawer-section">
        <ScanSearch size={23} />
        <KeyValues values={values} />
      </div>
    </Drawer>
  );
}
