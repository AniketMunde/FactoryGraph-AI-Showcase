// API v1 projections. Runtime case validation uses the frozen Phase 6 JSON schema server-side.
export type Role = "operator" | "viewer";
export type Principal = {
  authenticated: true;
  username: string;
  role: Role;
  csrf: string;
  tag: string;
  scope: number[] | "registered_fleet";
};
export type Machine = { machine_id: number; model: string };
export type Snapshot = {
  snapshot: string;
  eligibility: "primary" | "evidence_only" | "saved_case";
};
export type Metadata = {
  api_version: string;
  mode: "full" | "gallery";
  banner: string;
  dataset: string;
  approved_predictor: string;
  phase5_decision: string;
  capabilities: {
    dynamic_replay: boolean;
    telemetry: boolean;
    gallery: boolean;
    max_fleet: number;
  };
  limitations: string[];
};
export type Fact = {
  id: string;
  machine_id: number;
  kind: "errors" | "maint" | "failures";
  code: string;
  event_timestamp: string;
  source_table: string;
  source_row: number;
  source_record_id: string;
  source_sha256: string;
  visibility_policy: string;
  [key: string]: unknown;
};
export type Recommendation = {
  rule_id: string;
  rule_version: string;
  trigger: string;
  supporting_evidence_ids: string[];
  basis: string;
  cutoff_exclusive: string;
  text: string;
  limitations: string;
  human_review_required: true;
};
export type ContextRecord = {
  record_id?: string;
  values?: Record<string, number | null>;
  forecast_issue_timestamp?: string;
  latest_residual_observation_timestamp?: string;
  latest_source_observation_timestamp?: string;
  forecast_context_last_observation_timestamp?: string;
  model_id?: string;
  checkpoint_revision?: string;
  artifact_sha256?: string;
  interpretation?: string;
  modifies_primary_probability?: false;
};
export type CaseReport = {
  schema_version: string;
  case_id: string;
  request: { machine_id: number; snapshot: string; mode: string };
  status: "complete" | "evidence_only" | "abstained" | "degraded";
  prediction: {
    status: string;
    reason: string | null;
    probability: number | null;
    horizon_hours: number;
    model_id: string | null;
    model_sha256: string | null;
    calibration_sha256: string | null;
    policy_sha256: string | null;
    record_id: string | null;
    [key: string]: unknown;
  };
  alert_policy: {
    status: string;
    threshold: number | null;
    cooldown_hours: number;
    above_threshold: boolean | null;
    new_alert: boolean | null;
    cooldown_suppressed: boolean | null;
    last_episode_timestamp: string | null;
    policy_sha256: string | null;
    record_id: string | null;
    scope: string;
  };
  historical_evidence: {
    status: string;
    reason?: string;
    source?: string;
    cutoff_exclusive?: string;
    window_start_inclusive?: string;
    machine?: {
      machine_id: number;
      model: string;
      age: number;
      record_id: string;
      source_table: string;
      source_row: number;
    } | null;
    facts?: Fact[];
    pagination?: {
      limit: number;
      returned: number;
      eligible_window_records: number;
      truncated: boolean;
    };
    derived_aggregates?: {
      record_id?: string;
      definition?: string;
      model_peers?: Machine[];
      lifetime_counts?: { kind: string; code: string; count: number }[];
      window_counts?: { kind: string; code: string; count: number }[];
      [key: string]: unknown;
    };
    visibility_assumption?: string;
  };
  temporal_context: {
    status: string;
    reason: string | null;
    approved_predictor_inputs?: ContextRecord | null;
    supplementary_chronos_context?: ContextRecord | null;
  };
  recommendations: Recommendation[];
  human_review_priority: string;
  explanation: string[];
  data_availability: {
    prediction: { status: string; reason: string | null };
    graph_evidence: { status: string; reason: string | null };
    temporal_context: { status: string; reason: string | null };
    [key: string]: unknown;
  };
  provenance: {
    graph: {
      namespace: string;
      schema_version: string;
      build_hash: string;
      verified_for_case: boolean;
    } | null;
    source_fact_ids: string[];
    availability_policy: string;
    dataset_identity: string;
    artifact_trust: string;
    [key: string]: unknown;
  };
  limitations: string[];
};
export type CaseEnvelope = {
  mode: "full" | "gallery";
  api_version: string;
  projection: string;
  report: CaseReport;
};
export type Telemetry = {
  machine_id: number;
  cutoff_exclusive: string;
  units: string;
  source_sha256: string;
  observations: {
    timestamp: string;
    volt: number;
    rotate: number;
    pressure: number;
    vibration: number;
  }[];
};
export type Metrics = {
  mode: string;
  startup_seconds: number;
  process_rss_bytes: number;
  result_cache: boolean;
  recent_requests: {
    request_id: string;
    route: string;
    status: number;
    duration_seconds: number;
    error_category: string | null;
  }[];
};
export type Workspace = "fleet" | "assets" | "alerts" | "machine" | "graph" | "system" | "research";
