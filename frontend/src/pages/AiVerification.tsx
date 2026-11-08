import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, PlugZap, RotateCcw, Save, Trash2, XCircle } from "lucide-react";
import { api } from "../lib/api";
import type { VlmEventType, VlmMode, VlmProviderId, VlmSettings, VlmUsageDay } from "../types";

// Admin: optional AI (VLM) check of each incident before or after it alerts (ADR 0001).
// Cloud (Claude / Gemini / OpenAI) or a local model (e.g. Qwen3-VL via Ollama or vLLM) - an admin setting.

const PROVIDERS: { id: VlmProviderId; label: string; modelHint: string; urlHint: string }[] = [
  { id: "anthropic", label: "Claude (Anthropic) - cloud", modelHint: "claude-sonnet-5-5 (default)", urlHint: "leave empty" },
  { id: "openai_compatible", label: "OpenAI-compatible - local (Ollama, vLLM, LM Studio) or OpenAI cloud",
    modelHint: "e.g. qwen3-vl:8b", urlHint: "e.g. http://localhost:11434/v1 (Ollama)" },
  { id: "google", label: "Gemini (Google) - cloud", modelHint: "Gemini model name", urlHint: "leave empty" },
];

const MODES: { id: VlmMode; label: string }[] = [
  { id: "off", label: "Off - straight to the dashboard" },
  { id: "annotate", label: "Annotate - alert now, AI verdict added after" },
  { id: "gate", label: "Gate - wait for the AI; no alert if it says false alarm" },
];

type Form = Omit<VlmSettings, "api_key_set" | "api_key_last4" | "secret_key_configured"> & { api_key: string };

function toForm(s: VlmSettings): Form {
  const { api_key_set: _a, api_key_last4: _b, secret_key_configured: _c, ...rest } = s;
  return { ...rest, api_key: "" };
}

function errText(err: any, fallback: string): string {
  const d = err?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return d.map((x: any) => x.msg).join("; ");
  return fallback;
}

export default function AiVerification() {
  const [settings, setSettings] = useState<VlmSettings | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [types, setTypes] = useState<VlmEventType[]>([]);
  const [openPrompt, setOpenPrompt] = useState<string | null>(null);
  const [usage, setUsage] = useState<{ days: VlmUsageDay[]; queue: number; today: VlmUsageDay | null } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [test, setTest] = useState<any>(null);

  const load = () => {
    api.get<VlmSettings>("/api/vlm/settings").then((r) => {
      setSettings(r.data);
      setForm(toForm(r.data));
    });
    api.get<VlmEventType[]>("/api/vlm/event-types").then((r) => setTypes(r.data));
    api.get("/api/vlm/usage").then((r) => setUsage(r.data));
  };
  useEffect(load, []);

  if (!settings || !form) return <div className="dm-skeleton h-64 max-w-4xl" />;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => f && { ...f, [k]: v });
  const provider = PROVIDERS.find((p) => p.id === form.provider)!;

  async function saveSettings(): Promise<boolean> {
    setBusy("save");
    setMessage(null);
    try {
      const { api_key, ...rest } = form!;
      const r = await api.put<VlmSettings>("/api/vlm/settings", { ...rest, ...(api_key ? { api_key } : {}) });
      setSettings(r.data);
      setForm(toForm(r.data));
      setMessage({ ok: true, text: "Saved." });
      return true;
    } catch (err) {
      setMessage({ ok: false, text: errText(err, "Failed to save") });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function testConnection() {
    if (!(await saveSettings())) return;
    setBusy("test");
    setTest(null);
    try {
      setTest((await api.post("/api/vlm/test")).data);
    } catch (err) {
      setTest({ ok: false, error: errText(err, "Test failed") });
    } finally {
      setBusy(null);
    }
  }

  async function removeKey() {
    if (!confirm("Remove the stored API key? AI verification with this provider stops until a new key is saved.")) return;
    const r = await api.delete<VlmSettings>("/api/vlm/settings/api-key");
    setSettings(r.data);
    setForm(toForm(r.data));
  }

  async function saveTypes() {
    setBusy("types");
    try {
      const r = await api.put<VlmEventType[]>(
        "/api/vlm/event-types",
        types.map((t) => ({ event_type: t.event_type, mode: t.mode, prompt_template: t.prompt_template })),
      );
      setTypes(r.data);
      setMessage({ ok: true, text: "Alert types saved." });
    } catch (err) {
      setMessage({ ok: false, text: errText(err, "Failed to save alert types") });
    } finally {
      setBusy(null);
    }
  }

  const today = usage?.today;

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-fg">AI Verification</h2>
        <p className="mt-1 text-sm text-muted">
          Optional. Before (or right after) an alert reaches the dashboard, a few frames go to an AI model that
          says whether it's really happening. Turn it off and every alert goes straight to the dashboard.
        </p>
      </div>

      {!settings.secret_key_configured && (
        <p className="rounded border border-warning/40 bg-warning/10 p-3 text-sm text-warning">
          TIAM_SECRET_KEY is not set on the server, so API keys can't be stored. Local models without a key still
          work. See CLAUDE.md (Commands) or config.ps1.
        </p>
      )}

      <section className="dm-card space-y-4 p-5">
        <label className="flex items-center gap-2 text-sm font-semibold text-fg">
          <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          Enable AI verification
        </label>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="dm-btn-secondary !py-1.5 text-xs"
            onClick={() => setForm((f) => f && { ...f, provider: "anthropic", base_url: null, model: "claude-sonnet-5-5", local_only: false })}>
            Cloud: Claude Sonnet 5.5
          </button>
          <button type="button" className="dm-btn-secondary !py-1.5 text-xs"
            onClick={() => setForm((f) => f && { ...f, provider: "openai_compatible", base_url: "http://localhost:11434/v1", model: "qwen3-vl:8b", local_only: true })}>
            Local: Ollama + Qwen3-VL 8B
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2 text-sm">
            <span className="dm-label">Provider</span>
            <select className="dm-input" value={form.provider} onChange={(e) => set("provider", e.target.value as VlmProviderId)}>
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="dm-label">Base URL</span>
            <input className="dm-input" value={form.base_url ?? ""} placeholder={provider.urlHint}
              onChange={(e) => set("base_url", e.target.value || null)} />
          </label>
          <label className="text-sm">
            <span className="dm-label">Model</span>
            <input className="dm-input" value={form.model ?? ""} placeholder={provider.modelHint}
              onChange={(e) => set("model", e.target.value || null)} />
          </label>
          <label className="col-span-2 text-sm">
            <span className="dm-label">API key {form.provider === "openai_compatible" && "(not needed for local servers)"}</span>
            <div className="flex gap-2">
              <input className="dm-input" type="password" autoComplete="off" value={form.api_key}
                disabled={!settings.secret_key_configured}
                placeholder={settings.api_key_set ? `Stored (ends in ${settings.api_key_last4 ?? "..."}) - leave empty to keep` : "Paste the key"}
                onChange={(e) => set("api_key", e.target.value)} />
              {settings.api_key_set && (
                <button type="button" className="dm-btn-secondary shrink-0" onClick={removeKey} title="Remove stored key">
                  <Trash2 className="h-4 w-4" /> Remove
                </button>
              )}
            </div>
            <span className="mt-1 flex items-center gap-1 text-xs text-muted">
              <KeyRound className="h-3 w-3" /> Stored encrypted; never shown again or sent to the browser.
            </span>
          </label>
          <label className="col-span-2 flex items-center gap-2 text-sm text-fg">
            <input type="checkbox" checked={form.local_only} onChange={(e) => set("local_only", e.target.checked)} />
            Local only - refuse any model server outside this network (video never leaves the site)
          </label>
        </div>

        <details className="text-sm">
          <summary className="cursor-pointer text-muted">Limits</summary>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {([
              ["gate_timeout_s", "Gate wait (s)", 1],
              ["timeout_s", "Request timeout (s)", 1],
              ["max_concurrent", "Calls at once", 1],
              ["max_calls_per_hour", "Max calls / hour", 1],
              ["min_confidence", "Min confidence (0-1)", 0.05],
              ["rejected_retention_days", "Keep rejected (days)", 1],
            ] as const).map(([k, label, step]) => (
              <label key={k} className="text-sm">
                <span className="dm-label">{label}</span>
                <input className="dm-input" type="number" step={step} value={form[k]}
                  onChange={(e) => set(k, Number(e.target.value) as never)} />
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">
            Over the hourly cap, on errors, or when the gate wait runs out, the alert still goes out marked
            "Unverified" - a real alert is never lost because the AI is slow or down.
          </p>
        </details>

        {message && <p className={`text-sm ${message.ok ? "text-success" : "text-critical"}`}>{message.text}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="dm-btn-primary" disabled={busy != null} onClick={saveSettings}>
            {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
          </button>
          <button type="button" className="dm-btn-secondary" disabled={busy != null} onClick={testConnection}>
            {busy === "test" ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Save &amp; test connection
          </button>
        </div>
        {test && (
          <div className={`rounded border p-3 text-sm ${test.ok ? "border-success/40 bg-success/10" : "border-critical/40 bg-critical/10"}`}>
            {test.ok ? (
              <span className="flex items-start gap-2 text-fg">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                Works: {test.model} answered "{test.verdict}" ({Number(test.confidence).toFixed(2)}) in {(test.latency_ms / 1000).toFixed(1)} s - {test.reason}
              </span>
            ) : (
              <span className="flex items-start gap-2 text-critical">
                <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> {test.error}
              </span>
            )}
          </div>
        )}
      </section>

      <section className="dm-card space-y-3 p-5">
        <h3 className="text-sm font-semibold text-fg">Per alert type</h3>
        <p className="text-xs text-muted">Only used while AI verification is enabled.</p>
        {types.map((t, i) => (
          <div key={t.event_type} className="border-t border-line pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm text-fg">{t.label}</span>
              <div className="flex items-center gap-2">
                <select className="dm-input !w-auto !py-1 text-sm" value={t.mode}
                  onChange={(e) => setTypes((ts) => ts.map((x, j) => (j === i ? { ...x, mode: e.target.value as VlmMode } : x)))}>
                  {MODES.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
                <button type="button" className="text-xs text-accent hover:underline"
                  onClick={() => setOpenPrompt(openPrompt === t.event_type ? null : t.event_type)}>
                  {openPrompt === t.event_type ? "Hide prompt" : "Edit prompt"}
                </button>
              </div>
            </div>
            {openPrompt === t.event_type && (
              <div className="mt-2 space-y-1">
                <textarea className="dm-input h-40 font-mono text-xs" value={t.prompt_template}
                  placeholder="Empty: the built-in default prompt is used (it reappears here after Save)."
                  onChange={(e) => setTypes((ts) => ts.map((x, j) => (j === i ? { ...x, prompt_template: e.target.value } : x)))} />
                <div className="flex items-center justify-between text-xs text-muted">
                  <span>Placeholders: {"{site_type} {camera} {zone} {local_time} {event_type} {reason}"}. Ask only about visible actions.</span>
                  <button type="button" className="flex items-center gap-1 text-accent hover:underline"
                    onClick={() => setTypes((ts) => ts.map((x, j) => (j === i ? { ...x, prompt_template: "" } : x)))}>
                    <RotateCcw className="h-3 w-3" /> Reset to default
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        <button type="button" className="dm-btn-primary" disabled={busy != null} onClick={saveTypes}>
          {busy === "types" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save alert types
        </button>
      </section>

      <section className="dm-card p-5">
        <h3 className="mb-3 text-sm font-semibold text-fg">Usage today</h3>
        {!today ? (
          <p className="text-sm text-muted">No calls yet today. Queue: {usage?.queue ?? 0}.</p>
        ) : (
          <div className="grid grid-cols-3 gap-3 text-sm sm:grid-cols-6">
            {([
              ["Calls", today.calls, "text-fg"], ["Avg time", `${(today.avg_latency_ms / 1000).toFixed(1)} s`, "text-fg"],
              ["Confirmed", today.confirmed, "text-critical"], ["Rejected", today.rejected, "text-success"],
              ["Uncertain", today.uncertain, "text-warning"], ["Errors / capped", `${today.errors} / ${today.skipped}`, "text-muted"],
            ] as const).map(([label, value, tone]) => (
              <div key={label}>
                <div className="text-xs text-muted">{label}</div>
                <div className={`text-2xl font-bold ${tone}`}>{value}</div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
