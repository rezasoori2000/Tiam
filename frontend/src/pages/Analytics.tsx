import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import { token } from "../lib/theme";
import type { BreachByDay, CameraLeaderboardEntry, RiskByPolicy } from "../types";

// Accent as the single hue: all three charts are single-measure, so no categorical palette.
const SEQUENTIAL_SUNSET = token("accent");
const MUTED_INK = token("text-muted");
const GRIDLINE = token("border");

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="dm-card p-5">
      <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      <div className="mt-4 h-64">{children}</div>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export default function Analytics() {
  const [byDay, setByDay] = useState<BreachByDay[]>([]);
  const [byPolicy, setByPolicy] = useState<RiskByPolicy[]>([]);
  const [leaderboard, setLeaderboard] = useState<CameraLeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<BreachByDay[]>("/api/analytics/breaches-by-day?days=30"),
      api.get<RiskByPolicy[]>("/api/analytics/risk-by-policy"),
      api.get<CameraLeaderboardEntry[]>("/api/analytics/camera-leaderboard"),
    ]).then(([d1, d2, d3]) => {
      setByDay(d1.data);
      setByPolicy(d2.data);
      setLeaderboard(d3.data);
      setLoading(false);
    });
  }, []);

  const totalBreaches = byDay.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">Analytics & Reports</h2>
        <p className="mt-1 text-sm text-slate-400">
          Site-wide breach trends, risk by policy type, and the camera leaderboard.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-slate-400">Loading analytics...</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="dm-card p-5">
              <div className="text-xs text-slate-500">Breaches (last 30 days)</div>
              <div className="mt-1 text-3xl font-semibold text-slate-100">{totalBreaches}</div>
            </div>
            <div className="dm-card p-5">
              <div className="text-xs text-slate-500">Policy types tracked</div>
              <div className="mt-1 text-3xl font-semibold text-slate-100">{byPolicy.length}</div>
            </div>
            <div className="dm-card p-5">
              <div className="text-xs text-slate-500">Cameras reporting</div>
              <div className="mt-1 text-3xl font-semibold text-slate-100">{leaderboard.length}</div>
            </div>
          </div>

          <ChartCard title="Breach count by day" subtitle="Last 30 days">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={byDay} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke={GRIDLINE} />
                <XAxis
                  dataKey="date"
                  tickFormatter={formatDate}
                  tick={{ fontSize: 11, fill: MUTED_INK }}
                  axisLine={{ stroke: GRIDLINE }}
                  tickLine={false}
                  interval={Math.max(0, Math.floor(byDay.length / 8))}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: MUTED_INK }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{ background: token("panel"), border: `1px solid ${token("border")}`, borderRadius: 4 }}
                  labelStyle={{ color: token("text") }}
                  itemStyle={{ color: token("text") }}
                  cursor={{ fill: token("panel-2") }}
                  labelFormatter={(v) => new Date(v as string).toLocaleDateString()}
                  formatter={(v: any) => [v, "Breaches"] as [number, string]}
                />
                <Bar dataKey="count" fill={SEQUENTIAL_SUNSET} radius={[2, 2, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <ChartCard title="Risk level by policy type" subtitle="Average risk score (0-10)">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byPolicy} margin={{ top: 4, right: 4, left: -20, bottom: 24 }}>
                  <CartesianGrid vertical={false} stroke={GRIDLINE} />
                  <XAxis
                    dataKey="policy_type"
                    tickFormatter={(v: string) => truncate(v, 14)}
                    tick={{ fontSize: 10, fill: MUTED_INK }}
                    axisLine={{ stroke: GRIDLINE }}
                    tickLine={false}
                    angle={-20}
                    textAnchor="end"
                    height={50}
                  />
                  <YAxis
                    domain={[0, 10]}
                    tick={{ fontSize: 11, fill: MUTED_INK }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{ background: token("panel"), border: `1px solid ${token("border")}`, borderRadius: 4 }}
                    labelStyle={{ color: token("text") }}
                    itemStyle={{ color: token("text") }}
                    cursor={{ fill: token("panel-2") }}
                    formatter={(v: any, _n: any, item: any) =>
                      [`${v} avg (n=${item.payload.count})`, item.payload.policy_type] as [string, string]
                    }
                  />
                  <Bar dataKey="avg_risk" fill={SEQUENTIAL_SUNSET} radius={[2, 2, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Camera leaderboard" subtitle="Total breaches by camera">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={leaderboard}
                  layout="vertical"
                  margin={{ top: 4, right: 24, left: 4, bottom: 0 }}
                >
                  <CartesianGrid horizontal={false} stroke={GRIDLINE} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: MUTED_INK }} axisLine={false} tickLine={false} />
                  <YAxis
                    dataKey="camera_name"
                    type="category"
                    width={110}
                    tick={{ fontSize: 12, fill: MUTED_INK }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{ background: token("panel"), border: `1px solid ${token("border")}`, borderRadius: 4 }}
                    labelStyle={{ color: token("text") }}
                    itemStyle={{ color: token("text") }}
                    cursor={{ fill: token("panel-2") }}
                    formatter={(v: any, _n: any, item: any) =>
                      [`${v} breaches, avg risk ${item.payload.avg_risk}`, item.payload.camera_name] as [string, string]
                    }
                  />
                  <Bar dataKey="total_events" fill={SEQUENTIAL_SUNSET} radius={[0, 2, 2, 0]} maxBarSize={28}>
                    {leaderboard.map((entry) => (
                      <Cell key={entry.camera_id} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        </>
      )}
    </div>
  );
}
