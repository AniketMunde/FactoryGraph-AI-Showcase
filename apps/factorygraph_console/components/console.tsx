"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Box,
  ChartNoAxesCombined,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Factory,
  FileCheck2,
  Grid2X2,
  Info,
  Layers3,
  LogOut,
  Menu,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import type {
  CaseEnvelope,
  CaseReport,
  Machine,
  Metadata,
  Metrics,
  Principal,
  Snapshot,
  Telemetry,
  Workspace,
} from "@/lib/contracts";
import { APIError, query, queue, request } from "@/lib/client";
import { countKind, percent, policy, readable, utc } from "@/lib/presentation";
import { AssetTable } from "./asset-table";
import { EvidenceDrawer, EvidenceGraph } from "./evidence-graph";
import { Login } from "./login";
import {
  Context,
  EvidenceSummary,
  Export,
  FullReport,
  Provenance,
  Recommendations,
  RiskSummary,
} from "./report";
import { Sensors } from "./sensors";
import { Badge, Button, Empty, ErrorState, KeyValues, Loading, Panel, TabBar } from "./ui";

const navigation = [
  { id: "fleet", label: "Fleet Overview", icon: Grid2X2 },
  { id: "assets", label: "Assets", icon: Box },
  { id: "alerts", label: "Alert Investigation", icon: TriangleAlert },
  { id: "machine", label: "Machine Intelligence", icon: ChartNoAxesCombined },
  { id: "graph", label: "Knowledge Graph Evidence", icon: Network },
  { id: "system", label: "System and Provenance", icon: Server },
  { id: "research", label: "Research Information", icon: BookOpen },
] as const;
const detailTabs = [
  { id: "sensors", label: "Sensor history" },
  { id: "errors", label: "Historical errors" },
  { id: "maint", label: "Maintenance events" },
  { id: "failures", label: "Prior failures" },
  { id: "chronos", label: "Chronos context" },
  { id: "provenance", label: "Provenance" },
];
const preferred = "2015-10-16T12:00:00+00:00";
export function Console() {
  const [principal, setPrincipal] = useState<Principal | null | undefined>(undefined);
  const [error, setError] = useState<unknown>();
  useEffect(() => {
    request<Principal | { authenticated: false }>("/api/session")
      .then((value) => setPrincipal(value.authenticated ? value : null))
      .catch(setError);
  }, []);
  if (error)
    return (
      <main className="standalone">
        <ErrorState error={error} retry={() => window.location.reload()} />
      </main>
    );
  if (principal === undefined)
    return (
      <main className="standalone">
        <Loading text="Verifying local console session…" />
      </main>
    );
  if (!principal) return <Login onLogin={setPrincipal} />;
  return (
    <WorkspaceConsole
      key={principal.tag}
      principal={principal}
      onLogout={() => setPrincipal(null)}
    />
  );
}
function WorkspaceConsole({ principal, onLogout }: { principal: Principal; onLogout: () => void }) {
  const [page, setPage] = useState<Workspace>("fleet");
  const [machine, setMachine] = useState(principal.role === "viewer" ? 17 : 1);
  const [snapshot, setSnapshot] = useState(preferred);
  const [tab, setTab] = useState("sensors");
  const [evidence, setEvidence] = useState<string | null>(null);
  const [selectionReady, setSelectionReady] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [meta, setMeta] = useState<Metadata>();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [ready, setReady] = useState<boolean | null>(null);
  const [bootError, setBootError] = useState<unknown>();
  const [healthError, setHealthError] = useState<unknown>();
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshotTotal, setSnapshotTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [eligibility, setEligibility] = useState("primary");
  const [snapshotError, setSnapshotError] = useState<unknown>();
  const [loadedReport, setReport] = useState<CaseReport>();
  const [caseError, setCaseError] = useState<unknown>();
  const [caseLoading, setCaseLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [fleet, setFleet] = useState<{ snapshot: string; mode: string; reports: CaseReport[] }>();
  const [fleetBusy, setFleetBusy] = useState(false);
  const [fleetError, setFleetError] = useState<unknown>();
  const [cohort, setCohort] = useState(3);
  const [caseFilter, setCaseFilter] = useState("all");
  const [caseSearch, setCaseSearch] = useState("");
  const [metrics, setMetrics] = useState<Metrics>();
  const [metricsError, setMetricsError] = useState<unknown>();
  const [metricsLoading, setMetricsLoading] = useState(false);
  const serial = useRef(queue());
  const caseCache = useRef(new Map<string, Promise<CaseEnvelope>>());
  const sensorCache = useRef(new Map<string, Promise<Telemetry>>());
  const activeKey = useRef("");
  const report =
    loadedReport &&
    loadedReport.request.machine_id === machine &&
    Date.parse(loadedReport.request.snapshot) === Date.parse(snapshot)
      ? loadedReport
      : undefined;
  const authFailure = useCallback(
    (error: unknown) => {
      if (error instanceof APIError && error.status === 401) {
        caseCache.current.clear();
        sensorCache.current.clear();
        onLogout();
      }
      return error;
    },
    [onLogout],
  );
  // The mount is keyed to the server-issued session tag. User/role changes discard all data.
  useEffect(() => {
    function readLocation() {
      const qs = new URLSearchParams(window.location.search);
      const requested = qs.get("workspace") as Workspace;
      if (navigation.some((n) => n.id === requested)) setPage(requested);
      const m = Number(qs.get("machine"));
      if (Number.isInteger(m) && m > 0) setMachine(m);
      const s = qs.get("snapshot");
      if (s && Number.isFinite(Date.parse(s))) setSnapshot(s);
      const t = qs.get("tab");
      if ((t && detailTabs.some((x) => x.id === t)) || t === "report") setTab(t!);
      setEvidence(qs.get("evidence"));
      setSelectionReady(true);
    }
    readLocation();
    window.addEventListener("popstate", readLocation);
    return () => window.removeEventListener("popstate", readLocation);
  }, []);
  useEffect(() => {
    if (!selectionReady) return;
    const qs = new URLSearchParams({ workspace: page, machine: String(machine), snapshot, tab });
    if (evidence) qs.set("evidence", evidence);
    window.history.replaceState(null, "", `?${qs}`);
  }, [page, machine, snapshot, tab, evidence, selectionReady]);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const metadata = await request<Metadata>("/api/data/metadata");
        const catalog = await request<{ total: number; items: Machine[] }>(
          "/api/data/machines?limit=100",
        );
        if (active) {
          setMeta(metadata);
          setMachines(catalog.items);
        }
      } catch (e) {
        if (active) setBootError(authFailure(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [principal.tag]); // eslint-disable-line
  const refreshReadiness = useCallback(async () => {
    try {
      await request("/api/data/readiness");
      setReady(true);
      setHealthError(undefined);
    } catch (e) {
      setReady(false);
      setHealthError(authFailure(e));
    }
  }, [authFailure]);
  useEffect(() => {
    void refreshReadiness();
  }, [principal.tag]); // eslint-disable-line
  useEffect(() => {
    if (!meta || !selectionReady) return;
    let active = true;
    setSnapshotError(undefined);
    request<{ total: number; items: Snapshot[] }>(
      query("snapshots", { machine_id: machine, offset, limit: 200, eligibility }),
    )
      .then((value) => {
        if (active) {
          setSnapshots(value.items);
          setSnapshotTotal(value.total);
          if (!snapshot && value.items[0]) setSnapshot(value.items[0].snapshot);
        }
      })
      .catch((e) => {
        if (active) {
          setSnapshotError(authFailure(e));
          setSnapshots([]);
        }
      });
    return () => {
      active = false;
    };
  }, [meta, machine, offset, eligibility, selectionReady]); // eslint-disable-line
  const getCase = useCallback(
    (id: number, cutoff: string, force = false) => {
      const key = `${principal.tag}/${principal.role}/${meta?.mode}/${id}/${cutoff}`;
      if (force) caseCache.current.delete(key);
      let result = caseCache.current.get(key);
      if (!result) {
        result = serial.current(() =>
          request<CaseEnvelope>(query("case", { machine_id: id, snapshot_time: cutoff })),
        );
        caseCache.current.set(key, result);
        result.catch(() => caseCache.current.delete(key));
        if (caseCache.current.size > 32)
          caseCache.current.delete(caseCache.current.keys().next().value!);
      }
      return result;
    },
    [principal.tag, principal.role, meta?.mode],
  );
  useEffect(() => {
    if (!meta || !snapshot || !selectionReady || ["fleet", "assets", "research"].includes(page))
      return;
    let active = true;
    const key = `${machine}/${snapshot}`;
    activeKey.current = key;
    setCaseLoading(true);
    setCaseError(undefined);
    setReport(undefined);
    getCase(machine, snapshot)
      .then((value) => {
        if (active && activeKey.current === key) setReport(value.report);
      })
      .catch((e) => {
        if (active) setCaseError(authFailure(e));
      })
      .finally(() => {
        if (active) setCaseLoading(false);
      });
    return () => {
      active = false;
    };
  }, [meta?.mode, machine, snapshot, page, selectionReady, refresh, getCase]); // eslint-disable-line
  const loadTelemetry = useCallback(
    (hours: number, force = false) => {
      const key = `${principal.tag}/${principal.role}/${meta?.mode}/${machine}/${snapshot}/${hours}`;
      if (force) sensorCache.current.delete(key);
      let result = sensorCache.current.get(key);
      if (!result) {
        result = serial.current(() =>
          request<Telemetry>(
            query("telemetry", { machine_id: machine, snapshot_time: snapshot, hours }),
          ),
        );
        sensorCache.current.set(key, result);
        result.catch(() => sensorCache.current.delete(key));
        if (sensorCache.current.size > 12)
          sensorCache.current.delete(sensorCache.current.keys().next().value!);
      }
      return result;
    },
    [principal.tag, principal.role, meta?.mode, machine, snapshot],
  );
  function go(target: Workspace) {
    window.history.pushState(null, "", window.location.href);
    setPage(target);
    setMobileNav(false);
    setEvidence(null);
    requestAnimationFrame(() => document.getElementById("workspace-title")?.focus());
  }
  const open = useCallback((id: number) => {
    setMachine(id);
    setOffset(0);
    go("alerts");
  }, []);
  async function replay() {
    if (!meta) return;
    setFleetBusy(true);
    setFleetError(undefined);
    try {
      const result = await serial.current(() =>
        request<{ mode: string; reports: CaseReport[] }>("/api/data/fleet", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": principal.csrf },
          body: JSON.stringify({
            snapshot,
            machines: machines.slice(0, Math.min(cohort, machines.length)).map((m) => m.machine_id),
          }),
        }),
      );
      setFleet({ snapshot, mode: result.mode, reports: result.reports });
      for (const r of result.reports) {
        const key = `${principal.tag}/${principal.role}/${result.mode}/${r.request.machine_id}/${r.request.snapshot}`;
        caseCache.current.set(
          key,
          Promise.resolve({
            api_version: "v1",
            mode: result.mode as "full",
            projection: "sanitized-case-v1",
            report: r,
          }),
        );
        if (caseCache.current.size > 32) {
          caseCache.current.delete(caseCache.current.keys().next().value!);
        }
      }
    } catch (e) {
      setFleetError(authFailure(e));
    } finally {
      setFleetBusy(false);
    }
  }
  async function logout() {
    try {
      await request("/api/session", {
        method: "DELETE",
        headers: { "X-CSRF-Token": principal.csrf },
      });
    } finally {
      caseCache.current.clear();
      sensorCache.current.clear();
      onLogout();
    }
  }
  async function getMetrics() {
    setMetricsLoading(true);
    setMetricsError(undefined);
    try {
      setMetrics(await request<Metrics>("/api/data/metrics"));
    } catch (e) {
      setMetricsError(authFailure(e));
    } finally {
      setMetricsLoading(false);
    }
  }
  const reports = useMemo(
    () => (fleet?.snapshot === snapshot && fleet.mode === meta?.mode ? fleet.reports : []),
    [fleet, snapshot, meta?.mode],
  );
  const caseList = useMemo(() => {
    const values = new Map(reports.map((r) => [r.case_id, r]));
    if (report) values.set(report.case_id, report);
    return [...values.values()]
      .sort(
        (a, b) =>
          Number(Boolean(b.alert_policy.new_alert)) - Number(Boolean(a.alert_policy.new_alert)),
      )
      .filter(
        (r) =>
          (caseFilter === "all" || policy(r).key === caseFilter) &&
          String(r.request.machine_id).includes(caseSearch),
      );
  }, [reports, report, caseFilter, caseSearch]);
  const current = navigation.find((item) => item.id === page)!;
  const caseNeeded = !["fleet", "assets", "research"].includes(page);
  return (
    <div
      className={`console-shell ${collapsed ? "nav-collapsed" : ""} ${mobileNav ? "mobile-nav-open" : ""}`}
    >
      <a className="skip-link" href="#main-content">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Factory size={22} />
          </span>
          <span>
            FactoryGraph <b>AI</b>
            <small>OPERATIONS CONSOLE</small>
          </span>
        </div>
        <div className="nav-section-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`nav-item ${page === item.id ? "active" : ""}`}
                aria-current={page === item.id ? "page" : undefined}
                title={item.label}
                onClick={() => go(item.id)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
                {page === item.id && <span className="nav-marker" />}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="replay-card">
            <Database size={17} />
            <div>
              <strong>Historical research replay</strong>
              <small>Synthetic Azure benchmark</small>
            </div>
          </div>
          <button
            className="collapse-button"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            <span>Collapse navigation</span>
          </button>
          <div className="sidebar-version">
            <span>CONSOLE v2.0</span>
            <span>LOCAL</span>
          </div>
        </div>
      </aside>
      {mobileNav && (
        <button
          className="mobile-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNav(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            onClick={() => setMobileNav(!mobileNav)}
            aria-label="Open navigation"
          >
            <Menu size={21} />
          </button>
          <div className="breadcrumb">
            Operations <ChevronRight size={13} />
            <strong>{current.label}</strong>
          </div>
          <div className="topbar-right">
            <span className="topbar-note">
              <ShieldCheck size={14} />
              Authenticated local workspace
            </span>
            <div className="role-chip">
              <span className="avatar">{principal.role === "operator" ? "OP" : "VW"}</span>
              <div>
                <strong>{principal.role === "operator" ? "Operator" : "Viewer"}</strong>
                <small>
                  {principal.role === "operator"
                    ? meta?.mode === "gallery"
                      ? "Saved-case scope"
                      : "Registered fleet scope"
                    : "Machine 17 only"}
                </small>
              </div>
            </div>
            <button className="icon-button" onClick={logout} aria-label="Sign out">
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <div className="selection-bar">
          <div className="dataset-label">
            <span className="square-mark">
              <Layers3 size={16} />
            </span>
            <div>
              <strong>Azure predictive maintenance</strong>
              <small>
                {meta?.mode === "gallery"
                  ? "Explicit saved-case gallery"
                  : "Historical synthetic replay"}
              </small>
            </div>
          </div>
          <div className="selection-controls">
            <label>
              Machine
              <select
                aria-label="Selected machine"
                value={machine}
                onChange={(e) => {
                  setMachine(Number(e.target.value));
                  setOffset(0);
                  setEvidence(null);
                }}
              >
                {!machines.some((m) => m.machine_id === machine) && (
                  <option value={machine}>Machine {machine}</option>
                )}
                {machines.map((m) => (
                  <option key={m.machine_id} value={m.machine_id}>
                    Machine {String(m.machine_id).padStart(2, "0")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Eligibility
              <select
                aria-label="Snapshot eligibility"
                value={eligibility}
                onChange={(e) => {
                  setEligibility(e.target.value);
                  setOffset(0);
                  setSnapshot("");
                }}
              >
                <option value="primary">Approved score</option>
                <option value="evidence_only">Evidence only</option>
                <option value="all">All supported</option>
              </select>
            </label>
            <label className="snapshot-control">
              <span>
                <Clock3 size={12} />
                Historical snapshot · UTC
              </span>
              <select
                aria-label="Historical snapshot UTC"
                value={snapshot}
                onChange={(e) => {
                  setSnapshot(e.target.value);
                  setEvidence(null);
                }}
              >
                {snapshot && !snapshots.some((s) => s.snapshot === snapshot) && (
                  <option value={snapshot}>{utc(snapshot)}</option>
                )}
                {snapshots.map((s) => (
                  <option key={s.snapshot} value={s.snapshot}>
                    {utc(s.snapshot)}
                  </option>
                ))}
              </select>
            </label>
            <div className="snapshot-pages">
              <button
                className="icon-button"
                aria-label="Earlier snapshot page"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 200))}
              >
                <ChevronLeft size={14} />
              </button>
              <button
                className="icon-button"
                aria-label="Later snapshot page"
                disabled={offset + 200 >= snapshotTotal}
                onClick={() => setOffset(offset + 200)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
          <button
            className="readiness"
            onClick={refreshReadiness}
            title="Refresh actual API/graph readiness"
          >
            <span className={ready ? "verified-dot" : "unverified-dot"} />
            {ready === null
              ? "Checking backend"
              : ready
                ? meta?.mode === "gallery"
                  ? "API ready ? gallery"
                  : "API / graph ready"
                : "Backend unavailable"}
          </button>
        </div>
        <main id="main-content" className="content">
          <div className="research-strip">
            <Info size={14} />
            <span>
              Retrospective synthetic research demonstration. Not validated for operational
              machinery decisions.
            </span>
            <span className="scope-tag">API v1 · {meta?.mode ?? "checking"}</span>
          </div>
          <div className="workspace-heading">
            <div>
              <p className="eyebrow">
                {page === "fleet"
                  ? "THE FLEET, IN CONTEXT"
                  : page === "alerts"
                    ? "FROM ALERT TO EVIDENCE"
                    : "SOURCE-GROUNDED INVESTIGATION"}
              </p>
              <h1 id="workspace-title" tabIndex={-1}>
                {current.label}
              </h1>
              <p>
                {page === "fleet"
                  ? "A snapshot-scoped view of your registered machines and frozen policy decisions."
                  : page === "alerts"
                    ? "Review the model decision. Follow the evidence. Keep the human in control."
                    : `Machine ${machine} · ${snapshot ? utc(snapshot) : "Choose a supported snapshot"}`}
              </p>
            </div>
            <div className="heading-actions">
              {caseNeeded && (
                <Button
                  onClick={() => {
                    caseCache.current.clear();
                    sensorCache.current.clear();
                    setRefresh((v) => v + 1);
                    void refreshReadiness();
                  }}
                  disabled={caseLoading}
                >
                  <RefreshCw size={14} />
                  Refresh case
                </Button>
              )}
              {report && caseNeeded && <Export report={report} />}
            </div>
          </div>
          {bootError ? (
            <ErrorState error={bootError} retry={() => window.location.reload()} />
          ) : !meta ? (
            <Loading text="Loading authorized API metadata…" />
          ) : (
            <>
              {Boolean(snapshotError) && <ErrorState error={snapshotError} />}{" "}
              {Boolean(healthError) && <ErrorState error={healthError} retry={refreshReadiness} />}{" "}
              {(page === "fleet" || page === "assets") && (
                <>
                  <div className="stats-grid">
                    {[
                      {
                        label:
                          meta.mode === "gallery" ? "Saved-case machines" : "Registered machines",
                        value: machines.length,
                        detail:
                          meta.mode === "gallery"
                            ? "Explicit gallery membership"
                            : "Within your authorized scope",
                        icon: Factory,
                      },
                      {
                        label: "Represented in replay",
                        value: reports.length,
                        detail: reports.length
                          ? "Exact selected UTC cutoff"
                          : "Run a bounded replay to score",
                        icon: Layers3,
                      },
                      {
                        label: "New policy alerts",
                        value: reports.length
                          ? reports.filter((r) => r.alert_policy.new_alert).length
                          : "—",
                        detail: "Generated alert episodes",
                        icon: TriangleAlert,
                        tone: "danger",
                      },
                      {
                        label: "Cooldown suppressed",
                        value: reports.length
                          ? reports.filter((r) => r.alert_policy.cooldown_suppressed).length
                          : "—",
                        detail: "Repeat threshold crossings",
                        icon: Clock3,
                        tone: "amber",
                      },
                      {
                        label: "Below threshold",
                        value: reports.length
                          ? reports.filter(
                              (r) =>
                                r.prediction.status === "verified" &&
                                !r.alert_policy.above_threshold,
                            ).length
                          : "—",
                        detail: "Not an equipment safety status",
                        icon: Activity,
                      },
                      {
                        label: "Evidence / unavailable",
                        value: reports.length
                          ? reports.filter((r) => r.prediction.status !== "verified").length
                          : "—",
                        detail: "No borrowed model score",
                        icon: FileCheck2,
                      },
                    ].map((stat) => (
                      <div className={`stat ${stat.tone ?? ""}`} key={stat.label}>
                        <div>
                          <span>{stat.label}</span>
                          <stat.icon size={16} />
                        </div>
                        <strong>{stat.value}</strong>
                        <small>{stat.detail}</small>
                      </div>
                    ))}
                  </div>
                  <Panel
                    title={page === "assets" ? "Authorized asset catalog" : "Fleet command center"}
                    eyebrow={
                      snapshot ? `REPLAY CUTOFF · ${utc(snapshot)}` : "SELECT A SUPPORTED SNAPSHOT"
                    }
                    action={
                      <div className="replay-actions">
                        <label>
                          Cohort
                          <select
                            aria-label="Replay cohort size"
                            value={cohort}
                            onChange={(e) => setCohort(Number(e.target.value))}
                          >
                            {[1, 3, 10, 100].map((n) => (
                              <option key={n} value={n}>
                                {n} machine{n > 1 ? "s" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                        <Button
                          variant="primary"
                          onClick={replay}
                          disabled={fleetBusy || !snapshot || !meta.capabilities.dynamic_replay}
                        >
                          <RefreshCw size={14} className={fleetBusy ? "spin" : ""} />
                          {fleetBusy ? "Replaying…" : "Run verified replay"}
                        </Button>
                      </div>
                    }
                  >
                    {fleetBusy && (
                      <Loading
                        text={`Building genuine historical cases for ${Math.min(cohort, machines.length)} authorized machines. Large cohorts may take tens of seconds…`}
                      />
                    )}{" "}
                    {Boolean(fleetError) && <ErrorState error={fleetError} retry={replay} />}
                    <AssetTable machines={machines} reports={reports} open={open} />
                    <div className="panel-note">
                      <Info size={14} />
                      Counts apply only to returned replay reports. Unscored rows are metadata, not
                      healthy machines. Model categories are not physical dependencies.
                    </div>
                  </Panel>
                  <div className="workflow-guide">
                    <div>
                      <ScanIcon />
                      <strong>Start with a machine. Follow the source.</strong>
                      <p>
                        Run a replay, open an investigation, inspect historical evidence, then
                        export the verified report.
                      </p>
                    </div>
                    <Button onClick={() => go("alerts")}>
                      Investigate selected machine
                      <ArrowRight size={15} />
                    </Button>
                  </div>
                </>
              )}
              {caseNeeded &&
                (caseLoading ? (
                  <Loading />
                ) : caseError ? (
                  <ErrorState error={caseError} retry={() => setRefresh((v) => v + 1)} />
                ) : !report ? (
                  <Empty title="Select a supported historical snapshot">
                    A verified report will appear after its exact machine/time key is accepted.
                  </Empty>
                ) : (
                  <>
                    {page === "alerts" && (
                      <div className="investigation-layout">
                        <Panel
                          title="Replay cases"
                          eyebrow="SELECTED CUTOFF ONLY"
                          className="case-list-panel"
                        >
                          <div className="case-filters">
                            <div className="search-input">
                              <Search size={14} />
                              <input
                                aria-label="Search replay cases"
                                placeholder="Machine ID…"
                                value={caseSearch}
                                onChange={(e) => setCaseSearch(e.target.value)}
                              />
                            </div>
                            <select
                              aria-label="Filter investigation state"
                              value={caseFilter}
                              onChange={(e) => setCaseFilter(e.target.value)}
                            >
                              <option value="all">All policy outcomes</option>
                              <option value="alert">New policy alerts</option>
                              <option value="cooldown">Cooldown suppressed</option>
                              <option value="below">Below threshold</option>
                              <option value="evidence">Evidence only</option>
                            </select>
                          </div>
                          <div className="case-items">
                            {caseList.length ? (
                              caseList.map((c) => (
                                <button
                                  key={c.case_id}
                                  className={`case-item ${c.case_id === report.case_id ? "selected" : ""}`}
                                  onClick={() => {
                                    setMachine(c.request.machine_id);
                                    setSnapshot(c.request.snapshot);
                                  }}
                                >
                                  <div>
                                    <strong>
                                      Machine {String(c.request.machine_id).padStart(2, "0")}
                                    </strong>
                                    <ArrowUpRight size={14} />
                                  </div>
                                  <Badge tone={policy(c).tone}>{policy(c).label}</Badge>
                                  <span className="case-probability">
                                    {percent(c.prediction.probability, 4)}
                                  </span>
                                  <small>{utc(c.request.snapshot, true)}</small>
                                  <small>Evidence {c.historical_evidence.status}</small>
                                </button>
                              ))
                            ) : (
                              <Empty title="No matching replay cases">
                                Adjust the outcome filter.
                              </Empty>
                            )}
                          </div>
                          <p className="panel-note">
                            This bounded list contains the selected replay and requested case. It is
                            not a persistent incident register.
                          </p>
                        </Panel>
                        <div className="investigation-main">
                          <div className="machine-heading">
                            <span className="machine-avatar">
                              <Factory size={24} />
                            </span>
                            <div>
                              <h2>Machine {String(report.request.machine_id).padStart(2, "0")}</h2>
                              <p>
                                {report.historical_evidence.machine?.model ?? "Model unavailable"} ·{" "}
                                {utc(report.request.snapshot)}
                              </p>
                            </div>
                            <Badge
                              tone={
                                report.historical_evidence.status === "verified"
                                  ? "verified"
                                  : "muted"
                              }
                            >
                              Evidence {report.historical_evidence.status}
                            </Badge>
                          </div>
                          <div className="investigation-steps">
                            <span className="active">
                              <Check size={13} />
                              Policy decision
                            </span>
                            <button onClick={() => go("machine")}>
                              Sensor history
                              <ArrowUpRight size={12} />
                            </button>
                            <button onClick={() => go("graph")}>
                              Graph evidence
                              <ArrowUpRight size={12} />
                            </button>
                            <button onClick={() => setTab(tab === "report" ? "sensors" : "report")}>
                              Verified report
                              <ArrowUpRight size={12} />
                            </button>
                          </div>
                          {tab === "report" ? (
                            <FullReport report={report} onEvidence={setEvidence} />
                          ) : (
                            <>
                              <RiskSummary report={report} />
                              <EvidenceSummary report={report} onEvidence={setEvidence} />
                              <Recommendations report={report} onEvidence={setEvidence} />
                              <div className="limitation-note">
                                <ShieldCheck size={16} />
                                {report.limitations[0]}
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                    {page === "machine" && (
                      <>
                        <div className="asset-summary">
                          <div>
                            <Factory size={24} />
                            <div>
                              <h2>Machine {String(machine).padStart(2, "0")}</h2>
                              <p>
                                {report.historical_evidence.machine?.model ?? "Model unavailable"} ·
                                recorded model category
                              </p>
                            </div>
                          </div>
                          <div>
                            <span>Approved 24h estimate</span>
                            <strong>{percent(report.prediction.probability)}</strong>
                          </div>
                          <Badge tone={policy(report).tone}>{policy(report).label}</Badge>
                          <Badge
                            tone={
                              report.historical_evidence.status === "verified"
                                ? "verified"
                                : "muted"
                            }
                          >
                            Evidence {report.historical_evidence.status}
                          </Badge>
                        </div>
                        <TabBar
                          value={detailTabs.some((t) => t.id === tab) ? tab : "sensors"}
                          onChange={setTab}
                          items={detailTabs}
                        />
                        {tab === "chronos" ? (
                          <Context report={report} />
                        ) : tab === "provenance" ? (
                          <Provenance report={report} />
                        ) : detailTabs.some(
                            (t) => t.id === tab && ["errors", "maint", "failures"].includes(t.id),
                          ) ? (
                          <EventTable report={report} kind={tab} onEvidence={setEvidence} />
                        ) : (
                          <Sensors
                            machine={machine}
                            snapshot={snapshot}
                            load={loadTelemetry}
                            available={meta.capabilities.telemetry}
                          />
                        )}
                      </>
                    )}
                    {page === "graph" && (
                      <>
                        <EvidenceGraph report={report} onEvidence={setEvidence} />
                        <EventTable report={report} onEvidence={setEvidence} />
                      </>
                    )}
                    {page === "system" && (
                      <>
                        <div className="system-grid">
                          <Panel title="Service and access" action={<Server size={18} />}>
                            <div className="panel-body">
                              <KeyValues
                                values={{
                                  backend_readiness: ready ? "Verified ready" : "Unavailable",
                                  runtime_mode: meta.mode,
                                  API_version: meta.api_version,
                                  role: principal.role,
                                  authorized_scope: principal.scope,
                                  result_cache:
                                    "Session-local browser memory only; no cross-user cache",
                                  public_hosting: "Not enabled",
                                }}
                              />
                            </div>
                          </Panel>
                          <Panel
                            title="Approved model and policy"
                            action={<ShieldCheck size={18} />}
                          >
                            <div className="panel-body">
                              <KeyValues
                                values={{
                                  model: report.prediction.model_id,
                                  probability: report.prediction.probability,
                                  threshold: report.alert_policy.threshold,
                                  cooldown_hours: report.alert_policy.cooldown_hours,
                                  phase5_replacement: "NO-GO",
                                  C1: "Optional native optimization; original B remains default",
                                }}
                              />
                            </div>
                          </Panel>
                        </div>
                        <Provenance report={report} />
                        <Panel
                          title="Bounded request observations"
                          eyebrow="OPERATOR SCOPE ONLY"
                          action={
                            principal.role === "operator" ? (
                              <Button onClick={getMetrics} disabled={metricsLoading}>
                                Load authorized metrics
                                <RefreshCw size={14} />
                              </Button>
                            ) : (
                              <Badge tone="muted">Operator required</Badge>
                            )
                          }
                        >
                          {metricsLoading ? (
                            <Loading />
                          ) : metricsError ? (
                            <ErrorState error={metricsError} />
                          ) : metrics ? (
                            <>
                              <div className="panel-body">
                                <KeyValues
                                  values={{
                                    startup_seconds: metrics.startup_seconds,
                                    RSS_bytes: metrics.process_rss_bytes,
                                    scope:
                                      "Per-process observation; not isolated model memory or a production SLA",
                                  }}
                                />
                              </div>
                              <div className="table-scroll">
                                <table className="compact-table">
                                  <thead>
                                    <tr>
                                      <th>Route template</th>
                                      <th>Status</th>
                                      <th>Observed duration</th>
                                      <th>Request ID</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {metrics.recent_requests.map((m, i) => (
                                      <tr key={m.request_id + i}>
                                        <td className="mono">{m.route}</td>
                                        <td>{m.status}</td>
                                        <td>{(m.duration_seconds * 1000).toFixed(1)} ms</td>
                                        <td className="mono">{m.request_id.slice(0, 12)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </>
                          ) : (
                            <Empty
                              title={
                                principal.role === "operator"
                                  ? "Metrics are loaded on request"
                                  : "Metrics are not authorized for this role"
                              }
                            >
                              No operational measurements are invented or exposed through hidden
                              controls.
                            </Empty>
                          )}
                        </Panel>
                      </>
                    )}
                    <EvidenceDrawer
                      report={report}
                      id={evidence}
                      onClose={() => setEvidence(null)}
                    />
                  </>
                ))}
              {page === "research" && <Research meta={meta} />}
            </>
          )}
          <footer className="content-footer">
            <span>
              <ShieldCheck size={12} />
              Evidence grounded. Human review required.
            </span>
            <span>Historical replay · no autonomous machinery actions</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function ScanIcon() {
  return <FileCheck2 size={22} />;
}
function EventTable({
  report,
  kind,
  onEvidence,
}: {
  report: CaseReport;
  kind?: string;
  onEvidence: (id: string) => void;
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const records = [...(report.historical_evidence.facts ?? [])]
    .reverse()
    .filter(
      (f) =>
        (!kind || f.kind === kind) &&
        `${f.code} ${f.source_table} ${f.source_record_id}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
    );
  return (
    <Panel
      title={
        kind === "maint"
          ? "Recorded maintenance history"
          : kind === "failures"
            ? "Prior recorded failures"
            : kind === "errors"
              ? "Historical error records"
              : "Source event ledger"
      }
      eyebrow="RECORDED FACTS · NOT PREDICTED OUTCOMES"
      action={<span className="muted small">{records.length} returned records</span>}
    >
      <div className="table-toolbar">
        <div className="search-input">
          <Search size={15} />
          <input
            aria-label="Search historical evidence"
            placeholder="Search code or source record…"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <span className="muted small">Strictly before {utc(report.request.snapshot, true)}</span>
      </div>
      {report.historical_evidence.status !== "verified" ? (
        <Empty title="Historical evidence unavailable">This is not a verified empty history.</Empty>
      ) : !records.length ? (
        <Empty title="No matching returned source records">
          No diagnosis or equipment-safety conclusion follows from an empty bounded window.
        </Empty>
      ) : (
        <>
          <div className="table-scroll">
            <table className="compact-table">
              <thead>
                <tr>
                  <th>Event UTC</th>
                  <th>Record kind</th>
                  <th>Code</th>
                  <th>Source table</th>
                  <th>Source row</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {records.slice(page * 10, page * 10 + 10).map((f) => (
                  <tr key={f.id}>
                    <td className="tabular">{utc(f.event_timestamp)}</td>
                    <td>
                      {f.kind === "maint"
                        ? "Maintenance"
                        : f.kind === "errors"
                          ? "Error"
                          : "Prior failure"}
                    </td>
                    <td>
                      <span className="model-code">{f.code}</span>
                    </td>
                    <td className="mono">{f.source_table}</td>
                    <td>{f.source_row}</td>
                    <td>
                      <Button variant="ghost" onClick={() => onEvidence(f.id)}>
                        Source detail
                        <ArrowUpRight size={13} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-footer">
            <span>
              {report.historical_evidence.pagination?.truncated
                ? "API evidence truncated; pagination retained in full export"
                : "All API-returned rows retained in the verified export"}
            </span>
            <div>
              <Button
                aria-label="Previous event page"
                disabled={!page}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft size={14} />
              </Button>
              <Button
                aria-label="Next event page"
                disabled={(page + 1) * 10 >= records.length}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight size={14} />
              </Button>
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}
function Research({ meta }: { meta: Metadata }) {
  const items = [
    {
      n: "01",
      title: "One approved predictor",
      text: "Calibrated Phase 1 LightGBM is exactly equivalent to Phase 5 A0. Frozen probability, threshold and cooldown semantics are retained.",
    },
    {
      n: "02",
      title: "A negative replacement decision",
      text: "Phase 5 concluded NO-GO for replacing the approved predictor. Chronos and graph augmentation did not satisfy the prespecified operational criterion.",
    },
    {
      n: "03",
      title: "Separate temporal context",
      text: "Chronos supplies historical forecast summaries and matured residuals. Kumo remains a separate tabular comparison. Neither is promoted to the approved predictor here.",
    },
    {
      n: "04",
      title: "Source-grounded graph evidence",
      text: "Neo4j returns recorded historical source rows and model-category peer associations. These do not establish physical dependencies, diagnoses or causes.",
    },
    {
      n: "05",
      title: "Optional C1 runtime",
      text: "Phase 8's metadata index is an optional native serving optimization with preserved report semantics. This console retains original B by default; native improvements are not container claims.",
    },
    {
      n: "06",
      title: "A demonstration with limits",
      text: "The benchmark is synthetic Microsoft Azure historical data. MetroPT-3 evaluation remains incomplete. No prospective or real-machinery decision utility has been established.",
    },
  ];
  return (
    <>
      <Panel title="Research context, kept transparent" eyebrow="METHODS AND LIMITATIONS">
        <div className="research-intro">
          <BookOpen size={25} />
          <div>
            <h2>Confidence in the evidence. Clarity about the limits.</h2>
            <p>
              {meta.dataset}. This interface makes accepted research usable without turning
              retrospective results into operational promises.
            </p>
          </div>
        </div>
        <div className="research-grid">
          {items.map((item) => (
            <article key={item.n}>
              <span>{item.n}</span>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </article>
          ))}
        </div>
        <div className="panel-note">
          <Info size={15} />
          {meta.limitations.join(" · ")}
        </div>
      </Panel>
      <div className="research-decision">
        <Badge tone="amber">Phase 5 · NO-GO</Badge>
        <p>
          The approved baseline is retained. Every report preserves provenance, unknowns and the
          need for human review.
        </p>
      </div>
    </>
  );
}
