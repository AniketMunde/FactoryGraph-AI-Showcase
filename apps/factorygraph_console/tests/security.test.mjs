import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";
import http from "node:http";
import Ajv2020 from "ajv/dist/2020.js";

const project = resolve(process.cwd(), "../..");
const origin = "http://localhost:18601";
test("frozen report schema rejects corrupt exports", async () => {
  const schema = JSON.parse(await readFile(resolve(process.cwd(), "lib/case-schema.json"), "utf8"));
  const validate = new Ajv2020({ strict: false }).compile(schema);
  const reference = JSON.parse(
    await readFile(resolve(project, "tests/fixtures/illustrative_case.json"), "utf8"),
  );
  delete reference.temporal_context.supplementary_chronos_context.artifact_path;
  assert.equal(validate(reference), true);
  const missing = structuredClone(reference);
  delete missing.case_id;
  assert.equal(validate(missing), false);
  const invalid = structuredClone(reference);
  invalid.prediction.probability = 2;
  assert.equal(validate(invalid), false);
  const extra = structuredClone(reference);
  extra.unapproved_field = "forbidden";
  assert.equal(validate(extra), false);
});
const secrets = async (name) => (await readFile(resolve(project, name), "utf8")).trim();
async function call(path, { cookie, csrf, method = "GET", payload, headers = {}, raw } = {}) {
  const response = await fetch(origin + path, {
    method,
    headers: {
      ...(cookie ? { Cookie: cookie } : {}),
      ...(method !== "GET" ? { Origin: origin, "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...headers,
    },
    ...(payload !== undefined
      ? { body: JSON.stringify(payload) }
      : raw !== undefined
        ? { body: raw }
        : {}),
  });
  const body = await response.json();
  return { response, body };
}
async function login(role) {
  const password = await secrets(`artifacts/operations_console_v2/secrets/${role}.login`);
  const { response, body } = await call("/api/session", {
    method: "POST",
    payload: { username: role, password },
  });
  assert.equal(response.status, 200);
  const header = response.headers.get("set-cookie");
  assert.ok(
    header.includes("HttpOnly") && header.includes("Secure") && header.includes("SameSite=strict"),
  );
  assert.equal(body.role, role);
  return { cookie: header.split(";")[0], csrf: body.csrf };
}

test("genuine session, authorization, CSRF, schema parity and revocation boundaries", {
  skip: process.env.FG_PUBLIC_GENUINE_INTEGRATION !== "1",
}, async () => {
  assert.equal((await call("/api/data/metadata")).response.status, 401);
  assert.equal(
    (
      await call("/api/data/fleet", {
        method: "POST",
        payload: { snapshot: "2015-10-16T12:00Z", machines: [1] },
      })
    ).response.status,
    401,
  );
  assert.equal(
    (
      await call("/api/session", {
        method: "POST",
        headers: { Origin: "https://untrusted.invalid" },
        payload: { username: "operator", password: "invalid" },
      })
    ).response.status,
    403,
  );
  const operator = await login("operator"),
    viewer = await login("viewer");
  const catalog = await call("/api/data/machines", viewer);
  assert.equal(catalog.response.status, 200);
  assert.deepEqual(
    catalog.body.items.map((m) => m.machine_id),
    [17],
  );
  assert.equal(
    (await call("/api/data/case?machine_id=1&snapshot_time=2015-10-16T12:00Z", viewer)).response
      .status,
    403,
  );
  assert.equal((await call("/api/data/metrics", viewer)).response.status, 403);
  assert.equal((await call("/api/data/snapshots?machine_id=1", viewer)).response.status, 403);
  assert.equal(
    (await call("/api/data/case?machine_id=17&snapshot_time=2015-10-16T12:00Z", viewer)).response
      .status,
    200,
  );
  const membership = { snapshot: "2015-10-16T12:00Z", machines: [17, 1] };
  assert.equal(
    (await call("/api/data/fleet", { ...viewer, method: "POST", payload: membership })).response
      .status,
    403,
  );
  assert.equal(
    (
      await call("/api/data/fleet", {
        cookie: operator.cookie,
        method: "POST",
        payload: { ...membership, machines: [1] },
      })
    ).response.status,
    403,
  );
  assert.equal(
    (
      await call("/api/data/fleet", {
        ...operator,
        method: "POST",
        headers: { Origin: "https://untrusted.invalid" },
        payload: membership,
      })
    ).response.status,
    403,
  );
  assert.equal(
    (
      await call("/api/data/fleet", {
        ...operator,
        method: "POST",
        payload: { snapshot: membership.snapshot, machines: [1, 1] },
      })
    ).response.status,
    422,
  );
  assert.equal((await call("/api/data/metadata?role=operator", viewer)).response.status, 422);
  assert.equal((await call("/api/data/machines?limit=1&limit=2", operator)).response.status, 422);
  assert.equal(
    (await call("/api/data/machines?path=../../.env.phase4", operator)).response.status,
    422,
  );
  assert.equal((await call("/api/data/arbitrary", operator)).response.status, 404);
  assert.equal((await call("/api/data/constructor", operator)).response.status, 404);
  assert.equal(
    (await call("/api/data/metadata", { ...operator, method: "POST", payload: {} })).response
      .status,
    405,
  );
  assert.equal(
    (
      await call("/api/data/metadata", {
        ...operator,
        headers: { Origin: "https://untrusted.invalid" },
      })
    ).response.status,
    403,
  );
  const badHost = await new Promise((resolve, reject) => {
    http
      .get(
        origin + "/api/data/metadata",
        { headers: { Host: "untrusted.invalid", Cookie: operator.cookie } },
        (r) => {
          r.resume();
          resolve(r.statusCode);
        },
      )
      .on("error", reject);
  });
  assert.equal(badHost, 400);
  assert.equal(
    (await call("/api/data/fleet", { ...operator, method: "POST", raw: "{bad" })).response.status,
    422,
  );
  assert.equal(
    (await call("/api/data/fleet", { ...operator, method: "POST", raw: "x".repeat(17000) }))
      .response.status,
    413,
  );
  assert.equal(
    (await call("/api/data/case?machine_id=10001&snapshot_time=2015-10-16T12:00Z", operator))
      .response.status,
    404,
  );
  assert.equal(
    (await call("/api/data/case?machine_id=1&snapshot_time=2015-10-16T12:01Z", operator)).response
      .status,
    404,
  );
  assert.equal(
    (await call("/api/data/case?machine_id=1&snapshot_time=2015-10-16T12:00", operator)).response
      .status,
    422,
  );
  const reference = JSON.parse(
    await readFile(resolve(project, "docs/examples/phase6/new_alert.json"), "utf8"),
  );
  delete reference.temporal_context.supplementary_chronos_context.artifact_path;
  const accepted = await call(
    "/api/data/case?machine_id=1&snapshot_time=2015-10-16T12:00Z",
    operator,
  );
  assert.equal(accepted.response.status, 200);
  assert.deepEqual(accepted.body.report, reference);
  assert.equal(accepted.body.report.prediction.probability, 0.9998306894970957);
  assert.equal(accepted.body.report.alert_policy.threshold, 0.9996602309282403);
  assert.equal(accepted.body.report.alert_policy.new_alert, true);
  assert.ok(accepted.response.headers.get("cache-control").includes("no-store"));
  assert.equal(accepted.response.headers.get("x-frame-options"), "DENY");
  for (const file of ["operator", "viewer"]) {
    const token = await secrets(`artifacts/phase7/secrets/${file}.token`);
    assert.equal(JSON.stringify(accepted.body).includes(token), false);
  }
  const direct = await fetch(
    "http://127.0.0.1:18080/api/v1/cases/1?snapshot_time=2015-10-16T12:00Z",
    {
      headers: {
        Authorization: `Bearer ${await secrets("artifacts/phase7/secrets/viewer.token")}`,
      },
    },
  );
  assert.equal(direct.status, 403);
  assert.equal((await call("/api/session", { ...viewer, method: "DELETE" })).response.status, 200);
  assert.equal((await call("/api/data/metadata", viewer)).response.status, 401);
  assert.equal(
    (await call("/api/session", { ...operator, method: "DELETE" })).response.status,
    200,
  );
  assert.equal((await call("/api/data/metadata", operator)).response.status, 401);
});
