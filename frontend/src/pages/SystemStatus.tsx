import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Camera, SystemMetrics } from "../types";

const POLL_MS = 3000;

// Admin: is the server keeping up? Per-camera processed fps / processing time, GPU, disk.
export default function SystemStatus() {
  const [m, setM] = useState<SystemMetrics | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((r) => setCameras(r.data)).catch(() => {});
    const load = () =>
      api
        .get<SystemMetrics>("/api/system/metrics")
        .then((r) => {
          setM(r.data);
          setError(null);
        })
        .catch(() => setError("Couldn't load system metrics"));
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, []);

  const name = (id: number) => cameras.find((c) => c.id === id)?.name ?? `Camera ${id}`;

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-fg">System</h2>
        <p className="mt-1 text-sm text-muted">Live processing load of this server. Refreshes every 3 s.</p>
      </div>
      {error && <p className="text-sm text-critical">{error}</p>}
      {!m ? (
        <div className="dm-skeleton h-40" />
      ) : (
        <>
          <section className="dm-card p-5">
            <h3 className="mb-3 text-sm font-semibold text-fg">Cameras</h3>
            {m.cameras.length === 0 ? (
              <p className="text-sm text-muted">No camera workers running.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr>
                    <th className="pb-2 font-medium">Camera</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2 text-right font-medium">Processed fps</th>
                    <th className="pb-2 text-right font-medium">ms / frame</th>
                    <th className="pb-2 text-right font-medium">Frames</th>
                    <th className="pb-2 text-right font-medium">Incidents</th>
                  </tr>
                </thead>
                <tbody>
                  {m.cameras.map((c) => (
                    <tr key={c.camera_id} className="border-t border-line">
                      <td className="py-1.5 text-fg">{name(c.camera_id)}</td>
                      <td className="py-1.5 text-muted">{c.status}</td>
                      <td className="py-1.5 text-right">{c.fps.toFixed(1)}</td>
                      <td className={`py-1.5 text-right ${c.process_ms > 100 ? "text-warning" : ""}`}>
                        {c.process_ms.toFixed(0)}
                      </td>
                      <td className="py-1.5 text-right">{c.frames}</td>
                      <td className="py-1.5 text-right">{c.incidents}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <div className="grid gap-4 sm:grid-cols-2">
            <section className="dm-card p-5">
              <h3 className="mb-3 text-sm font-semibold text-fg">GPU</h3>
              {m.gpus.length === 0 ? (
                <p className="text-sm text-muted">No GPU info (no NVIDIA driver?).</p>
              ) : (
                m.gpus.map((g) => {
                  const pct = Math.round((g.memory_used_mb / g.memory_total_mb) * 100);
                  return (
                    <div key={g.name} className="space-y-1 text-sm">
                      <div className="text-fg">{g.name}</div>
                      <div className="text-muted">
                        Memory {g.memory_used_mb} / {g.memory_total_mb} MB ({pct}%) · Load {g.utilization_pct}%
                      </div>
                      <div className="h-1.5 rounded bg-panel-2">
                        <div
                          className={`h-1.5 rounded ${pct > 90 ? "bg-critical" : "bg-accent"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })
              )}
              <p className="mt-3 text-xs text-muted">
                Models loaded: {m.models_loaded.length ? m.models_loaded.join(", ") : "none yet"}
              </p>
            </section>

            <section className="dm-card p-5">
              <h3 className="mb-3 text-sm font-semibold text-fg">Storage</h3>
              <p className="text-sm text-fg">
                {m.disk_free_gb} GB free of {m.disk_total_gb} GB
              </p>
              <ul className="mt-2 space-y-1 text-sm text-muted">
                {Object.entries(m.data_folders).map(([folder, mb]) => (
                  <li key={folder} className="flex justify-between">
                    <span className="font-mono text-xs">{folder}</span>
                    <span>{mb} MB</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">AI verification queue: not enabled yet (phase 2).</p>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
