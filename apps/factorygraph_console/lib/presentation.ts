import type { CaseReport } from "./contracts";
export const utc = (value: string, compact = false) =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    ...(compact ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value)) + " UTC";
export const percent = (p: number | null | undefined, digits = 6) =>
  p == null ? "Unavailable" : `${(p * 100).toFixed(digits)}%`;
export function policy(report?: CaseReport) {
  if (!report) return { key: "unscored", label: "Not replayed", tone: "muted" };
  if (report.prediction.status !== "verified")
    return {
      key: "evidence",
      label: report.status === "abstained" ? "Abstained" : "Evidence only",
      tone: "muted",
    };
  if (report.alert_policy.new_alert)
    return { key: "alert", label: "New policy alert", tone: "danger" };
  if (report.alert_policy.cooldown_suppressed)
    return { key: "cooldown", label: "Cooldown suppressed", tone: "amber" };
  return { key: "below", label: "Below threshold", tone: "neutral" };
}
export function facts(report?: CaseReport) {
  return report?.historical_evidence.facts ?? [];
}
export function latestEvent(report?: CaseReport) {
  return [...facts(report)].sort(
    (a, b) => Date.parse(b.event_timestamp) - Date.parse(a.event_timestamp),
  )[0];
}
export function countKind(report: CaseReport, kind: string) {
  return facts(report).filter((f) => f.kind === kind).length;
}
export const readable = (value: string | null | undefined) =>
  value?.replaceAll("_", " ") ?? "Unavailable";
