import "server-only";
import { readFile } from "node:fs/promises";
import Ajv2020 from "ajv/dist/2020";
import { z } from "zod";
import { NextRequest, NextResponse } from "next/server";
import schema from "@/lib/case-schema.json";
import { authorize, body, csrf, rate, reject, session } from "./security";

const validate = new Ajv2020({ strict: false, allErrors: false }).compile(schema);
const positive = z.coerce.number().int().min(1).max(1000000);
const snapshot = z
  .string()
  .max(40)
  .regex(/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|\+00:00)$/)
  .refine((v) => Number.isFinite(Date.parse(v)));
const paged = {
  offset: z.coerce.number().int().min(0).max(10000).optional(),
  limit: z.coerce.number().int().min(1).max(200).optional(),
};
const queries = {
  metadata: z.object({}).strict(),
  readiness: z.object({}).strict(),
  metrics: z.object({}).strict(),
  machines: z
    .object({ offset: paged.offset, limit: z.coerce.number().int().min(1).max(100).optional() })
    .strict(),
  snapshots: z
    .object({
      machine_id: positive,
      ...paged,
      eligibility: z.enum(["primary", "all", "evidence_only"]).optional(),
    })
    .strict(),
  case: z.object({ machine_id: positive, snapshot_time: snapshot }).strict(),
  telemetry: z
    .object({
      machine_id: positive,
      snapshot_time: snapshot,
      hours: z.coerce.number().int().min(1).max(168),
    })
    .strict(),
  fleet: z.object({}).strict(),
};
type Resource = keyof typeof queries;
const allowedErrors = new Set([
  "authentication_required",
  "rate_limit",
  "machine_not_authorized",
  "unknown_machine",
  "unsupported_snapshot",
  "invalid_utc_snapshot",
  "service_busy",
  "case_deadline_exceeded",
  "dependency_unavailable",
  "dependency_degraded",
  "capability_not_available_in_gallery",
  "fleet_requires_primary_snapshots",
  "invalid_request",
  "operator_required",
]);

export async function data(request: NextRequest, resourceName: string) {
  const principal = session(request);
  rate(principal);
  if (!Object.hasOwn(queries, resourceName)) reject(404, "unsupported_resource");
  const resource = resourceName as Resource;
  if ((resource === "fleet") !== (request.method === "POST")) reject(405, "method_not_allowed");
  if (resource === "metrics" && principal.role !== "operator") reject(403, "operator_required");
  const pairs = [...request.nextUrl.searchParams.entries()];
  if (new Set(pairs.map(([key]) => key)).size !== pairs.length) reject(422, "duplicate_query");
  const parsed = queries[resource].safeParse(Object.fromEntries(pairs));
  if (!parsed.success) reject(422, "invalid_request");
  const query = parsed.data as Record<string, string | number>;
  if (query.machine_id) authorize(principal, Number(query.machine_id));
  let payload: { snapshot: string; machines: number[] } | undefined;
  if (resource === "fleet") {
    csrf(request, principal);
    const result = z
      .object({ snapshot, machines: z.array(positive).min(1).max(100) })
      .strict()
      .safeParse(await body(request));
    if (!result.success || new Set(result.data.machines).size !== result.data.machines.length)
      reject(422, "invalid_request");
    payload = result.data;
    payload.machines.forEach((m) => authorize(principal, m));
  }
  const base = process.env.FG_CONSOLE_API_URL ?? "http://127.0.0.1:18080";
  if (!/^http:\/\/127\.0\.0\.1:(18080|18082|18083|18089)$/.test(base))
    reject(503, "backend_configuration_unavailable");
  const file =
    process.env[
      principal.role === "operator" ? "FG7_OPERATOR_TOKEN_FILE" : "FG7_VIEWER_TOKEN_FILE"
    ];
  if (!file) reject(503, "backend_credential_unavailable");
  const credential = (await readFile(file, "utf8")).trim();
  if (credential.length < 32 || credential.length > 256 || /\s/.test(credential))
    reject(503, "backend_credential_unavailable");
  const paths: Record<Resource, string> = {
    metadata: "/metadata",
    readiness: "/health/ready",
    machines: "/machines",
    snapshots: "/snapshots",
    case: `/cases/${query.machine_id}`,
    telemetry: `/telemetry/${query.machine_id}`,
    fleet: "/fleet/replay",
    metrics: "/metrics",
  };
  const target = new URL(base + "/api/v1" + paths[resource]);
  for (const [key, value] of Object.entries(query))
    if (!(key === "machine_id" && ["case", "telemetry"].includes(resource)))
      target.searchParams.set(key, String(value));
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: payload ? "POST" : "GET",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(125000),
      headers: {
        Authorization: `Bearer ${credential}`,
        ...(payload ? { "Content-Type": "application/json" } : {}),
      },
      ...(payload ? { body: JSON.stringify(payload) } : {}),
    });
  } catch {
    reject(503, "api_unreachable");
  }
  const value = await upstream.json().catch(() => reject(503, "invalid_backend_response"));
  if (!upstream.ok) {
    const code =
      typeof value.error === "string" && allowedErrors.has(value.error)
        ? value.error
        : "backend_request_rejected";
    return NextResponse.json(
      { error: code, request_id: typeof value.request_id === "string" ? value.request_id : null },
      {
        status: [401, 403, 404, 409, 413, 422, 429, 503, 504].includes(upstream.status)
          ? upstream.status
          : 503,
      },
    );
  }
  if (
    resource === "case" &&
    (!validate(value.report) || JSON.stringify(value).includes('"artifact_path"'))
  )
    reject(503, "invalid_backend_report");
  if (
    resource === "case" &&
    (value.report.request.machine_id !== query.machine_id ||
      Date.parse(value.report.request.snapshot) !== Date.parse(String(query.snapshot_time)))
  )
    reject(503, "mismatched_backend_report");
  if (
    resource === "fleet" &&
    (!Array.isArray(value.reports) ||
      !value.reports.every((r: unknown) => validate(r)) ||
      JSON.stringify(value).includes('"artifact_path"'))
  )
    reject(503, "invalid_backend_report");
  if (
    resource === "fleet" &&
    (value.reports.length !== payload!.machines.length ||
      value.reports.some(
        (r: { request: { machine_id: number; snapshot: string } }, i: number) =>
          r.request.machine_id !== payload!.machines[i] ||
          Date.parse(r.request.snapshot) !== Date.parse(payload!.snapshot),
      ))
  )
    reject(503, "mismatched_backend_report");
  if (resource === "telemetry") {
    const cutoff = Date.parse(String(query.snapshot_time));
    if (
      value.machine_id !== query.machine_id ||
      Date.parse(value.cutoff_exclusive) !== cutoff ||
      !Array.isArray(value.observations) ||
      value.observations.some(
        (r: { timestamp: string }) =>
          !Number.isFinite(Date.parse(r.timestamp)) ||
          Date.parse(r.timestamp) >= cutoff ||
          Date.parse(r.timestamp) < cutoff - Number(query.hours) * 3600000,
      )
    )
      reject(503, "invalid_telemetry_clock");
  }
  if (
    resource === "machines" &&
    principal.role === "viewer" &&
    value.items.some((r: { machine_id: number }) => r.machine_id !== 17)
  )
    reject(503, "invalid_authorization_response");
  if (resource === "metrics")
    return NextResponse.json({
      mode: value.mode,
      startup_seconds: value.startup_seconds,
      process_rss_bytes: value.process_rss_bytes,
      result_cache: value.result_cache,
      recent_requests: value.recent_requests.slice(-20),
    });
  return NextResponse.json(value);
}
