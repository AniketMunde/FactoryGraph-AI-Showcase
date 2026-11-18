"use client";
import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, ArrowUpRight } from "lucide-react";
import type { Telemetry } from "@/lib/contracts";
import { utc } from "@/lib/presentation";
import { Button, Empty, ErrorState, Loading, Panel } from "./ui";
const channels = [
  { key: "volt", name: "Voltage", source: "volt", color: "#2563a6" },
  { key: "rotate", name: "Rotation", source: "rotate", color: "#287f78" },
  { key: "pressure", name: "Pressure", source: "pressure", color: "#7b5cb1" },
  { key: "vibration", name: "Vibration", source: "vibration", color: "#b66b13" },
] as const;
export function Sensors({
  machine,
  snapshot,
  load,
  available,
}: {
  machine: number;
  snapshot: string;
  load: (hours: number, force?: boolean) => Promise<Telemetry>;
  available: boolean;
}) {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<Telemetry | null>(null);
  const [error, setError] = useState<unknown>();
  const [version, setVersion] = useState(0);
  const forceNext = useRef(false);
  useEffect(() => {
    if (!available) return;
    let active = true;
    setData(null);
    setError(undefined);
    const force = forceNext.current;
    forceNext.current = false;
    load(hours, force)
      .then((v) => {
        if (active) setData(v);
      })
      .catch((e) => {
        if (active) setError(e);
      });
    return () => {
      active = false;
    };
  }, [machine, snapshot, hours, version, load, available]);
  if (!available)
    return (
      <Empty title="Telemetry unavailable in this mode">
        Gallery cases do not expose arbitrary source measurements.
      </Empty>
    );
  const end = Date.parse(snapshot),
    start = end - hours * 3600000;
  const byTime = new Map(data?.observations.map((row) => [Date.parse(row.timestamp), row]));
  const points = Array.from({ length: hours }, (_, i) => {
    const ms = start + i * 3600000;
    return {
      ms,
      ...(byTime.get(ms) ?? { volt: null, rotate: null, pressure: null, vibration: null }),
    };
  });
  return (
    <>
      <div className="section-intro">
        <div>
          <h2>Measured sensor history</h2>
          <p>Original source channels · observations strictly before the selected cutoff.</p>
        </div>
        <div className="segmented" aria-label="Historical telemetry range">
          {[24, 72, 168].map((h) => (
            <button key={h} aria-pressed={h === hours} onClick={() => setHours(h)}>
              {h}h
            </button>
          ))}
        </div>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => setVersion((v) => v + 1)} />
      ) : !data ? (
        <Loading text="Loading verified source measurements…" />
      ) : !data.observations.length ? (
        <Empty title="No eligible measurements">
          No historical measurements are exposed in this window. This is not a zero reading.
        </Empty>
      ) : (
        <>
          <div className="sensor-meta">
            <span>
              <Activity size={14} />
              {data.observations.length} source observations
            </span>
            <span>
              {hours - data.observations.length > 0
                ? `${hours - data.observations.length} missing hourly opportunities`
                : "No missing hourly opportunities in this window"}
            </span>
            <span className="mono">
              {utc(new Date(start).toISOString(), true)} → {utc(snapshot, true)} (exclusive)
            </span>
          </div>
          <div className="sensor-grid">
            {channels.map((channel) => (
              <Panel
                key={channel.key}
                title={channel.name}
                eyebrow={`SOURCE CHANNEL · ${channel.source}`}
                action={<span className="chart-unit">Source units</span>}
              >
                <div
                  className="sensor-chart"
                  role="img"
                  aria-label={`${channel.name} historical telemetry, UTC, original source units, strictly before ${snapshot}`}
                >
                  <ResponsiveContainer width="100%" height={205}>
                    <LineChart
                      data={points}
                      syncId={`telemetry-${machine}-${snapshot}`}
                      margin={{ top: 18, right: 20, bottom: 8, left: 0 }}
                      accessibilityLayer
                    >
                      <CartesianGrid stroke="#e7edf2" vertical={false} />
                      <XAxis
                        dataKey="ms"
                        type="number"
                        domain={[start, end - 3600000]}
                        tickCount={4}
                        tickFormatter={(ms) =>
                          new Intl.DateTimeFormat("en-GB", {
                            timeZone: "UTC",
                            ...(hours > 24
                              ? { day: "2-digit" as const, month: "short" as const }
                              : {}),
                            hour: "2-digit",
                            minute: "2-digit",
                            hourCycle: "h23",
                          }).format(new Date(ms))
                        }
                        tick={{ fontSize: 11, fill: "#526377" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        width={50}
                        tick={{ fontSize: 11, fill: "#526377" }}
                        axisLine={false}
                        tickLine={false}
                        domain={["auto", "auto"]}
                      />
                      <Tooltip
                        labelFormatter={(value) => utc(new Date(Number(value)).toISOString())}
                        formatter={(value) => [Number(value).toFixed(5), channel.name]}
                        contentStyle={{
                          borderRadius: 6,
                          border: "1px solid #d7e0e8",
                          fontSize: 12,
                        }}
                        cursor={{ stroke: "#596e82", strokeDasharray: "3 3" }}
                      />
                      <Line
                        type="linear"
                        name={channel.name}
                        dataKey={channel.key}
                        stroke={channel.color}
                        strokeWidth={1.8}
                        dot={false}
                        activeDot={{ r: 4 }}
                        isAnimationActive={false}
                        connectNulls={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <footer className="chart-footer">
                  Shared UTC axis · gaps remain missing, never imputed
                </footer>
              </Panel>
            ))}
          </div>
          <div className="source-footer">
            <span>Verified telemetry source</span>
            <code>{data.source_sha256.slice(0, 24)}…</code>
            <Button
              variant="ghost"
              onClick={() => {
                forceNext.current = true;
                setVersion((v) => v + 1);
              }}
            >
              Refresh measurements
              <ArrowUpRight size={13} />
            </Button>
          </div>
        </>
      )}
    </>
  );
}
