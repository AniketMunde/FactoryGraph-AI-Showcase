"use client";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Dialog, Tabs } from "radix-ui";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { AlertTriangle, LoaderCircle, X } from "lucide-react";
import { APIError } from "@/lib/client";
export const cn = (...inputs: Parameters<typeof clsx>) => twMerge(clsx(inputs));
export function Button({
  className,
  variant = "secondary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  return <button className={cn("button", `button-${variant}`, className)} {...props} />;
}
export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true" className="status-dot" />
      {children}
    </span>
  );
}
export function Panel({
  title,
  eyebrow,
  action,
  children,
  className,
}: {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("panel", className)}>
      {title && (
        <header className="panel-header">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h2>{title}</h2>
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
export function Loading({ text = "Retrieving verified historical evidence…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={18} className="spin" />
      <span>{text}</span>
    </div>
  );
}
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof APIError ? error : new APIError(503, "request_unavailable");
  const descriptions: Record<string, string> = {
    service_busy: "The backend is processing another request. Retry once it has finished.",
    rate_limit: "The backend request limit was reached. Wait a minute before retrying.",
    console_rate_limit: "This session reached its request limit. Wait a minute before retrying.",
    dependency_unavailable:
      "Historical evidence is unavailable because a verified backend dependency could not be reached.",
    api_unreachable:
      "The configured API is unavailable. Full mode has not been replaced by gallery data.",
    case_deadline_exceeded:
      "The request exceeded its deadline. Its worker may still hold the compute slot.",
    unknown_machine: "This machine is not in the accepted registered scope.",
    unsupported_snapshot:
      "No report is supported at this exact timestamp. Select an eligible UTC snapshot.",
    machine_not_authorized: "This account is not authorized to access that machine.",
  };
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={21} />
      <div>
        <strong>Request unavailable · HTTP {e.status}</strong>
        <p>
          {descriptions[e.code] ??
            "The request could not be completed. No valid empty history or equipment status is inferred."}
        </p>
        <code>{e.code}</code>
        {e.requestId && <small>Request {e.requestId}</small>}
        {retry && <Button onClick={retry}>Retry request</Button>}
      </div>
    </div>
  );
}
export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      <p>{children}</p>
    </div>
  );
}
export function TabBar({
  value,
  onChange,
  items,
}: {
  value: string;
  onChange: (value: string) => void;
  items: { id: string; label: string }[];
}) {
  return (
    <Tabs.Root value={value} onValueChange={onChange}>
      <Tabs.List className="tabs" aria-label="Machine detail sections">
        {items.map((item) => (
          <Tabs.Trigger className="tab" key={item.id} value={item.id}>
            {item.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}
export function Drawer({
  title,
  children,
  open,
  onClose,
}: {
  title: string;
  children: ReactNode;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer">
          <header>
            <div>
              <p className="eyebrow">Verified evidence detail</p>
              <Dialog.Title>{title}</Dialog.Title>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close evidence detail">
              <X size={20} />
            </Dialog.Close>
          </header>
          <Dialog.Description className="muted">
            Source-backed fields and their historical visibility boundary. Derived projections are
            explicitly labeled.
          </Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function KeyValues({ values }: { values: Record<string, unknown> }) {
  return (
    <dl className="key-values">
      {Object.entries(values).map(([k, v]) => (
        <div key={k}>
          <dt>{k.replaceAll("_", " ")}</dt>
          <dd>
            {typeof v === "object" && v !== null ? (
              <pre>{JSON.stringify(v, null, 2)}</pre>
            ) : (
              String(v ?? "Unavailable")
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
