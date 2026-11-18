"use client";
import { useState, type FormEvent } from "react";
import { ArrowRight, Factory, LockKeyhole, ShieldCheck } from "lucide-react";
import { request } from "@/lib/client";
import type { Principal } from "@/lib/contracts";
import { Button, Loading } from "./ui";
export function Login({ onLogin }: { onLogin: (value: Principal) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const fields = new FormData(event.currentTarget);
    try {
      onLogin(
        await request<Principal>("/api/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: fields.get("username"),
            password: fields.get("password"),
          }),
        }),
      );
    } catch {
      setError(
        "Sign-in could not be completed. Check the local console credentials or wait if attempts are limited.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <div className="login-context">
        <div className="brand">
          <span className="brand-mark">
            <Factory size={23} />
          </span>
          <span>
            FactoryGraph <b>AI</b>
            <small>OPERATIONS CONSOLE</small>
          </span>
        </div>
        <div>
          <p className="eyebrow">Evidence before action</p>
          <h1>
            A clearer view.
            <br />A grounded decision.
          </h1>
          <p>
            Investigate historical machine alerts with verified predictions, source-backed evidence
            and traceable human-review guidance.
          </p>
          <div className="login-steps">
            <span>01 &nbsp; Select a replay</span>
            <span>02 &nbsp; Investigate the evidence</span>
            <span>03 &nbsp; Export the verified report</span>
          </div>
        </div>
        <small>
          Retrospective synthetic research demonstration.
          <br />
          Not validated for operational machinery decisions.
        </small>
      </div>
      <section className="login-form">
        <ShieldCheck size={28} />
        <p className="eyebrow">Local authenticated access</p>
        <h2>Open your workspace</h2>
        <p className="muted">Use your console account. Backend credentials stay on the server.</p>
        <form onSubmit={submit}>
          <label>
            Account
            <select name="username" aria-label="Account">
              <option value="operator">Operator · registered fleet</option>
              <option value="viewer">Viewer · Machine 17</option>
            </select>
          </label>
          <label>
            Console password
            <div className="password-field">
              <LockKeyhole size={17} />
              <input
                name="password"
                aria-label="Console password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={256}
              />
            </div>
          </label>
          {error && (
            <p role="alert" className="login-error">
              {error}
            </p>
          )}
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Enter operations console"}
            <ArrowRight size={16} />
          </Button>
        </form>
        {busy && <Loading text="Authenticating local session…" />}
        <p className="login-note">
          LOOPBACK ONLY · SECURE LOCAL SESSION
          <br />
          No public hosting or external identity provider is enabled.
        </p>
      </section>
    </main>
  );
}
