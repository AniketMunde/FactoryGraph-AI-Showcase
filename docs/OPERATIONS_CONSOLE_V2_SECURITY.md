# Operations Console v2 — local security boundary

The console is a new loopback-only Next.js application. Accepted FastAPI code and its
operator/viewer tokens remain unchanged. Browser login uses distinct newly generated
console passwords, never those backend tokens. Passwords are scrypt-hashed with separate
random salts in ignored server-side files. Successful login rotates the account's single
opaque server-side session. An eight-hour absolute expiry, bounded login attempts and
per-session data-request limits apply. Logout revokes the session. Restart revokes all
sessions; credential rotation requires restart. This is local demonstration identity,
not a reviewed public identity provider.

The host-only `__Host-fg_console` cookie is Secure, HttpOnly, SameSite=Strict and Path=/.
The canonical local origin is `http://localhost:18601`, with the process bound to
127.0.0.1. Browser localhost secure-context behavior must be verified in actual acceptance;
HTTPS/remote identity are not assumed. Host/origin/fetch-site checks apply before data
access. Login requires same-origin JSON; authenticated fleet/logout operations also
require a session-bound CSRF nonce. Bodies have explicit byte limits. No GET mutates data.

Every route handler authenticates its own session. The BFF has an explicit resource and
method allowlist, strict query/body validation, duplicate-key rejection, viewer Machine 17
authorization and operator-only metrics. Each role uses its own FastAPI credential;
FastAPI independently enforces authorization again. No arbitrary URL/path/query proxy
exists. Upstream redirects are disabled and backend destinations are fixed loopback ports.
Failures preserve bounded 429/503/504 contracts with sanitized messages. Full mode never
falls back to gallery. Original detailed reports are schema-validated and retained intact;
the internal temporal artifact path is forbidden in browser responses.

Credentials and user files live outside the frontend under ignored local artifacts.
Startup injects only file paths into the Node server environment. Build runs without
credentials; there are no credential `NEXT_PUBLIC` variables, browser storage tokens,
public secret copies or backend source-data mounts. The browser only calls same-origin
authenticated BFF endpoints. All responses use no-store, nosniff, frame denial and
no-referrer. CSP restricts sources to self; Next/React hydration currently requires inline
scripts/styles, so this is not a claim of a strict nonce CSP or public security acceptance.

Client caches are memory-only within one authenticated console instance and bounded by
exact machine, UTC cutoff, runtime mode and verified case identity. Logout/session expiry
clears the instance; no cross-user persistent data cache exists. Backend operations are
serialized in the client to respect the single compute slot. Explicit refresh bypasses
the client cache. Fleet results retain their exact timestamp/cohort and are never silently
reused for a new cutoff. Filtering/navigation do not issue new fleet computations.

Acceptance must exercise unauthenticated handlers, role tampering, resource denial,
CSRF/origin/host/input attacks, logout/revocation, secure cookies, build/browser secret
leakage, exact report export and genuine upstream failure semantics. Software injection
tests are separate from genuine source-backed acceptance. No public deployment, license
assignment or redistribution is authorized by this milestone.

Architecture follows the official Next.js guidance to authenticate route handlers as
[public security boundaries](https://nextjs.org/docs/app/guides/authentication) and keep
[sensitive data in the server layer](https://nextjs.org/docs/app/guides/data-security).
