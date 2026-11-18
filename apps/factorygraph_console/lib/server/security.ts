import "server-only";
import { createHash, randomBytes, scrypt, timingSafeEqual } from "node:crypto";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

export type Role = "operator" | "viewer";
type Account = { username: string; role: Role; salt: string; hash: string };
export type Session = {
  username: string;
  role: Role;
  csrf: string;
  expires: number;
  tag: string;
  requests: number[];
};
type State = { sessions: Map<string, Session>; loginAttempts: number[]; accounts?: Account[] };
const globalState = globalThis as unknown as { fgConsole?: State };
const state: State = (globalState.fgConsole ??= { sessions: new Map(), loginAttempts: [] });
export const COOKIE = "__Host-fg_console";
export const cookieOptions = {
  httpOnly: true,
  secure: true,
  sameSite: "strict" as const,
  path: "/",
};
function localOrigin() {
  const value = process.env.FG_CONSOLE_ORIGIN ?? "http://localhost:18601";
  if (!/^http:\/\/localhost:1860[1-5]$/.test(value)) reject(503, "invalid_console_origin");
  return value;
}
const derive = promisify(scrypt);
export class Rejection extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
export function reject(status: number, code: string): never {
  throw new Rejection(status, code);
}
export function boundary(request: NextRequest, mutation = false) {
  const origin = localOrigin();
  if (request.headers.get("host") !== new URL(origin).host) reject(400, "invalid_host");
  const supplied = request.headers.get("origin");
  if ((supplied && supplied !== origin) || request.headers.get("sec-fetch-site") === "cross-site")
    reject(403, "origin_not_allowed");
  if (mutation && supplied !== origin) reject(403, "origin_required");
}
export async function body(request: NextRequest, max = 16384): Promise<unknown> {
  if (request.headers.get("content-type")?.split(";")[0] !== "application/json")
    reject(415, "json_required");
  if (Number(request.headers.get("content-length") ?? 0) > max) reject(413, "request_too_large");
  const reader = request.body?.getReader();
  if (!reader) reject(422, "invalid_request");
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const part = await reader.read();
    if (part.done) break;
    size += part.value.length;
    if (size > max) {
      await reader.cancel();
      reject(413, "request_too_large");
    }
    chunks.push(part.value);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    reject(422, "invalid_json");
  }
}
function digest(value: string) {
  return createHash("sha256").update(value).digest("hex");
}
function equal(a: string, b: string) {
  const left = Buffer.from(a),
    right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}
function prune() {
  for (const [key, value] of state.sessions)
    if (value.expires <= Date.now()) state.sessions.delete(key);
}
export function session(request: NextRequest): Session {
  boundary(request);
  prune();
  const token = request.cookies.get(COOKIE)?.value;
  const result = token ? state.sessions.get(digest(token)) : undefined;
  if (!result) reject(401, "session_required");
  return result;
}
export function csrf(request: NextRequest, principal: Session) {
  boundary(request, true);
  if (!equal(request.headers.get("x-csrf-token") ?? "", principal.csrf))
    reject(403, "csrf_rejected");
}
export function authorize(principal: Session, machine: number) {
  if (principal.role === "viewer" && machine !== 17) reject(403, "machine_not_authorized");
}
export function rate(principal: Session) {
  principal.requests = principal.requests.filter((t) => Date.now() - t < 60000);
  if (principal.requests.length >= 120) reject(429, "console_rate_limit");
  principal.requests.push(Date.now());
}
export async function login(request: NextRequest) {
  boundary(request, true);
  state.loginAttempts = state.loginAttempts.filter((t) => Date.now() - t < 60000);
  if (state.loginAttempts.length >= 8) reject(429, "login_rate_limit");
  state.loginAttempts.push(Date.now());
  const input = z
    .object({ username: z.enum(["operator", "viewer"]), password: z.string().min(1).max(256) })
    .strict()
    .safeParse(await body(request, 4096));
  if (!input.success) reject(401, "invalid_credentials");
  if (!state.accounts) {
    const file = process.env.FG_CONSOLE_USERS_FILE;
    if (!file) reject(503, "console_identity_unavailable");
    const schema = z
      .array(
        z
          .object({
            username: z.enum(["operator", "viewer"]),
            role: z.enum(["operator", "viewer"]),
            salt: z.string().regex(/^[a-f0-9]{32}$/),
            hash: z.string().regex(/^[a-f0-9]{128}$/),
          })
          .strict(),
      )
      .length(2);
    state.accounts = schema.parse(JSON.parse(await readFile(file, "utf8")));
    if (
      new Set(state.accounts.map((a) => a.username)).size !== 2 ||
      state.accounts.some((a) => a.username !== a.role)
    )
      reject(503, "console_identity_unavailable");
  }
  const account = state.accounts.find((a) => a.username === input.data.username)!;
  const computed = (await derive(input.data.password, account.salt, 64)) as Buffer;
  if (!equal(computed.toString("hex"), account.hash)) reject(401, "invalid_credentials");
  prune();
  // One local session per account; successful reauthentication rotates/revokes the old session.
  for (const [key, value] of state.sessions)
    if (value.username === account.username) state.sessions.delete(key);
  const token = randomBytes(32).toString("hex");
  const principal: Session = {
    username: account.username,
    role: account.role,
    csrf: randomBytes(32).toString("hex"),
    expires: Date.now() + 8 * 3600000,
    tag: randomBytes(8).toString("hex"),
    requests: [],
  };
  state.sessions.set(digest(token), principal);
  const response = NextResponse.json({ authenticated: true, ...publicSession(principal) });
  response.cookies.set(COOKIE, token, { ...cookieOptions, maxAge: 8 * 3600 });
  return response;
}
export function publicSession(principal: Session) {
  return {
    username: principal.username,
    role: principal.role,
    csrf: principal.csrf,
    tag: principal.tag,
    scope: principal.role === "viewer" ? [17] : "registered_fleet",
  };
}
export function logout(request: NextRequest) {
  const principal = session(request);
  csrf(request, principal);
  state.sessions.delete(digest(request.cookies.get(COOKIE)!.value));
  const response = NextResponse.json({ authenticated: false });
  response.cookies.set(COOKIE, "", { ...cookieOptions, maxAge: 0 });
  return response;
}
export function failure(error: unknown) {
  if (error instanceof Rejection)
    return NextResponse.json({ error: error.code }, { status: error.status });
  return NextResponse.json({ error: "console_service_unavailable" }, { status: 503 });
}
