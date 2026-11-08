import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  Check,
  CheckCircle2,
  Clock,
  ImageOff,
  Loader2,
  Mail,
  Maximize2,
  MessageSquare,
  Minimize2,
  RotateCcw,
  Send,
  Undo2,
  X,
  XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import EventClip from "../components/EventClip";
import type { Camera, Event, EventComment, EventStatus } from "../types";

const TABS: { key: EventStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "to_review", label: "Open" },
  { key: "coached", label: "Resolved" },
];

// Stored statuses keep their old names; the UI says Open / Resolved (spec 9.3).
const STATUS_TEXT: Record<EventStatus, string> = { to_review: "Open", coached: "Resolved", dismissed: "Dismissed" };


const STATUS_BADGE: Record<EventStatus, string> = {
  to_review: "dm-pill-amber",
  coached: "dm-pill-emerald",
  dismissed: "dm-pill-slate",
};

export function riskColor(score: number): string {
  if (score >= 8) return "bg-red-500";
  if (score >= 5) return "bg-amber-500";
  return "bg-slate-500";
}

// Level is derived from the score (same bands as riskColor) so the two can never disagree.
export type RiskLevel = "Low" | "Medium" | "High";
export function riskLevel(score: number): RiskLevel {
  if (score >= 8) return "High";
  if (score >= 5) return "Medium";
  return "Low";
}
// Score range per level, used by the workbench level filter.
const LEVEL_RANGE: Record<RiskLevel, [number, number]> = { Low: [1, 4], Medium: [5, 7], High: [8, 10] };
// Score a reviewer gets when they pick a level rather than an exact score.
const LEVEL_SCORE: Record<RiskLevel, number> = { Low: 3, Medium: 6, High: 9 };

export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// The snapshot endpoint requires a login token, which a plain <img src="...">
// can't send as a header -- so this fetches it via axios (which attaches the
// token) and hands the browser a local blob: URL instead.
export function EventSnapshot({
  eventId,
  alt,
  className,
  iconClassName,
  zones = true,
}: {
  eventId: number;
  alt: string;
  className: string;
  iconClassName: string;
  zones?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    api
      .get(`/api/events/${eventId}/snapshot`, { params: { zones }, responseType: "blob" })
      .then((res) => {
        objectUrl = URL.createObjectURL(res.data as Blob);
        setUrl(objectUrl);
      })
      .catch(() => setFailed(true));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [eventId, zones]);

  if (failed || !url) {
    return (
      <div className="flex h-full w-full items-center justify-center text-muted">
        <ImageOff className={iconClassName} />
      </div>
    );
  }
  return <img src={url} alt={alt} className={className} />;
}

type SelectModifiers = { shift: boolean; toggle: boolean };

function EventCard({
  event,
  camera,
  selected,
  onClick,
  onDismiss,
}: {
  event: Event;
  camera?: Camera;
  selected: boolean;
  onClick: (mods: SelectModifiers) => void;
  onDismiss: () => void;
}) {
  function modsOf(e: ReactMouseEvent | ReactKeyboardEvent): SelectModifiers {
    return { shift: e.shiftKey, toggle: e.ctrlKey || e.metaKey };
  }

  return (
    // A div (not <button>) so the per-card Dismiss button can nest inside it.
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => onClick(modsOf(e))}
      // Stop shift-click from highlighting text across cards.
      onMouseDown={(e) => e.shiftKey && e.preventDefault()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(modsOf(e));
        }
      }}
      className={`dm-card group flex cursor-pointer select-none flex-col overflow-hidden text-left transition-colors ${
        selected ? "!border-apl-sunset ring-2 ring-apl-sunset" : "hover:border-slate-700"
      }`}
    >
      <div className="relative aspect-video bg-slate-900">
        {event.has_snapshot ? (
          <EventSnapshot
            eventId={event.id}
            alt={event.policy_type}
            className="h-full w-full object-cover"
            iconClassName="h-8 w-8"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-muted">
            <ImageOff className="h-8 w-8" />
          </div>
        )}
        <span className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-xs font-bold text-fg ${riskColor(event.risk_score)}`}>
          {riskLevel(event.risk_score)} · {event.risk_score}
        </span>
        {selected && (
          <span className="absolute left-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-apl-sunset text-fg">
            <Check className="h-4 w-4" />
          </span>
        )}
        {event.status !== "dismissed" && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDismiss();
            }}
            title="Dismiss (permanently deletes this event)"
            className="absolute bottom-2 right-2 flex items-center gap-1 rounded-full bg-black/70 px-2.5 py-1 text-xs font-medium text-slate-200 opacity-0 transition-opacity hover:bg-black/90 hover:text-fg focus:opacity-100 group-hover:opacity-100"
          >
            <XCircle className="h-3.5 w-3.5" /> Dismiss
          </button>
        )}
      </div>
      <div className="space-y-1 p-3">
        <div className="text-sm font-medium text-slate-100 line-clamp-1">{event.policy_type}</div>
        <div className="text-xs text-slate-500">
          {camera?.name ?? `Camera ${event.camera_id}`} &middot; {event.zone_name}
        </div>
        <div className="flex items-center justify-between pt-1">
          <span className={STATUS_BADGE[event.status]}>{STATUS_TEXT[event.status]}</span>
          <span className="flex items-center gap-1 text-xs text-slate-500">
            <Clock className="h-3 w-3" /> {timeAgo(event.timestamp)}
          </span>
        </div>
      </div>
    </div>
  );
}

function rawPayloadDetails(event: Event): { label: string; value: string }[] {
  const p = event.raw_payload as Record<string, any>;
  const details: { label: string; value: string }[] = [];
  if (p.speed_kmh != null) details.push({ label: "Detected speed", value: `${p.speed_kmh.toFixed(1)} km/h` });
  if (p.limit_kmh != null) details.push({ label: "Speed limit", value: `${p.limit_kmh} km/h` });
  if (p.distance_m != null) details.push({ label: "Distance", value: `${p.distance_m.toFixed(1)} m` });
  if (p.min_distance_m != null) details.push({ label: "Required min distance", value: `${p.min_distance_m} m` });
  if (p.vehicles_visited != null) {
    details.push({ label: "Cars checked", value: String(p.vehicles_visited) });
    details.push({ label: "Prowling score", value: `${p.score} (alert at ${p.threshold})` });
    if (Array.isArray(p.visits) && p.visits.length) {
      details.push({
        label: "Visits",
        value: p.visits
          .map((v: any) => `car #${v.vehicle_track_id} ${v.seconds}s${v.crouch_seconds >= 2 ? ` (crouched ${v.crouch_seconds}s)` : ""}`)
          .join(" · "),
      });
    }
  }
  if (event.track_id != null) details.push({ label: "Track ID", value: String(event.track_id) });
  return details;
}

function EmailIncidentModal({
  event,
  camera,
  onClose,
}: {
  event: Event;
  camera?: Camera;
  onClose: () => void;
}) {
  const cameraLabel = camera?.name ?? `Camera ${event.camera_id}`;
  const [toAddress, setToAddress] = useState("");
  const [subject, setSubject] = useState(`Incident: ${event.policy_type} - ${cameraLabel}`);
  const [body, setBody] = useState(
    `Incident type: ${event.policy_type}\n` +
      `Camera: ${cameraLabel}\n` +
      `Zone: ${event.zone_name}\n` +
      `Date/Time: ${new Date(event.timestamp).toLocaleString()}\n` +
      `Risk: ${riskLevel(event.risk_score)} (${event.risk_score} / 10)`
  );
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSending(true);
    try {
      await api.post(`/api/events/${event.id}/email`, { to_address: toAddress, subject, body });
      setSent(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to send email");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <form onSubmit={handleSubmit} className="dm-card w-full max-w-lg space-y-4 p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-100">Email incident snapshot</h3>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X className="h-4 w-4" />
          </button>
        </div>

        {sent ? (
          <>
            <p className="text-sm text-emerald-400">Email sent to {toAddress}.</p>
            <div className="flex justify-end">
              <button type="button" onClick={onClose} className="dm-btn-secondary">
                Close
              </button>
            </div>
          </>
        ) : (
          <>
            <label className="block text-sm">
              <span className="dm-label">To</span>
              <input
                required
                type="email"
                autoFocus
                value={toAddress}
                onChange={(e) => setToAddress(e.target.value)}
                placeholder="name@example.com"
                className="dm-input"
              />
            </label>
            <label className="block text-sm">
              <span className="dm-label">Subject</span>
              <input
                required
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="dm-input"
              />
            </label>
            <label className="block text-sm">
              <span className="dm-label">Message</span>
              <textarea
                required
                rows={6}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="dm-input"
              />
            </label>

            {error && <p className="text-sm text-red-400">{error}</p>}

            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="dm-btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={sending} className="dm-btn-primary">
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                Send
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

export function EventDetail({
  event, camera, onClose, onStatusChange, onRiskChange,
}: {
  event: Event;
  camera?: Camera;
  onClose: () => void;
  onStatusChange: (id: number, status: EventStatus) => void;
  onRiskChange: (id: number, riskScore: number) => void;
}) {
  const [comments, setComments] = useState<EventComment[]>([]);
  const [commentText, setCommentText] = useState("");
  const [posting, setPosting] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [showZones, setShowZones] = useState(true);

  useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen]);

  const loadComments = useCallback(() => {
    api.get<EventComment[]>(`/api/events/${event.id}/comments`).then((res) => setComments(res.data));
  }, [event.id]);

  useEffect(() => {
    loadComments();
  }, [loadComments]);

  async function handleAddComment() {
    if (!commentText.trim()) return;
    setPosting(true);
    try {
      await api.post(`/api/events/${event.id}/comments`, { text: commentText });
      setCommentText("");
      loadComments();
    } finally {
      setPosting(false);
    }
  }

  const details = rawPayloadDetails(event);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="dm-card flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden !rounded-xl bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <h3 className="font-semibold text-slate-100">{event.policy_type}</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto p-5">
          <div
            className={
              fullscreen
                ? "fixed inset-0 z-[60] bg-black"
                : "relative aspect-video overflow-hidden rounded-lg bg-apl-midnight"
            }
          >
            {event.has_snapshot ? (
              <EventSnapshot
                eventId={event.id}
                alt={event.policy_type}
                className="h-full w-full object-contain"
                iconClassName="h-10 w-10"
                zones={showZones}
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-muted">
                <ImageOff className="h-10 w-10" />
              </div>
            )}
            {event.has_snapshot && (
              <label className="absolute bottom-2 left-2 flex cursor-pointer items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 text-xs text-slate-200">
                <button
                  type="button"
                  role="switch"
                  aria-checked={showZones}
                  onClick={() => setShowZones((v) => !v)}
                  className={`relative h-4 w-7 rounded-full transition-colors ${
                    showZones ? "bg-apl-sunset" : "bg-slate-600"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-3 w-3 rounded-full bg-fg transition-all ${
                      showZones ? "left-3.5" : "left-0.5"
                    }`}
                  />
                </button>
                <span>Show zones</span>
              </label>
            )}
            {event.has_snapshot && (
              <button
                type="button"
                onClick={() => setFullscreen((f) => !f)}
                title={fullscreen ? "Exit full screen (Esc)" : "View full screen"}
                aria-label={fullscreen ? "Exit full screen" : "View full screen"}
                className="absolute bottom-2 right-2 flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-slate-200 hover:bg-black/80 hover:text-apl-sunset"
              >
                {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
            )}
          </div>

          {event.has_clip && (
            <div className="mt-4">
              <div className="mb-1 text-xs text-muted">Clip (10 s before to 10 s after)</div>
              <EventClip eventId={event.id} />
            </div>
          )}

          <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <div>
              <div className="text-xs text-slate-500">Camera</div>
              <div className="text-slate-200">{camera?.name ?? `Camera ${event.camera_id}`}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Zone</div>
              <div className="text-slate-200">{event.zone_name}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Risk</div>
              <div className="flex gap-1.5">
                <select
                  aria-label="Risk level"
                  className="dm-input !w-auto !px-2 !py-1"
                  value={riskLevel(event.risk_score)}
                  onChange={(e) => onRiskChange(event.id, LEVEL_SCORE[e.target.value as RiskLevel])}
                >
                  {(Object.keys(LEVEL_SCORE) as RiskLevel[]).map((level) => (
                    <option key={level}>{level}</option>
                  ))}
                </select>
                <select
                  aria-label="Risk score"
                  className="dm-input !w-auto !px-2 !py-1"
                  value={event.risk_score}
                  onChange={(e) => onRiskChange(event.id, Number(e.target.value))}
                >
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>{n} / 10</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <div className="text-xs text-slate-500">Time</div>
              <div className="text-slate-200">{new Date(event.timestamp).toLocaleString()}</div>
            </div>
            {details.map((d) => (
              <div key={d.label}>
                <div className="text-xs text-slate-500">{d.label}</div>
                <div className="text-slate-200">{d.value}</div>
              </div>
            ))}
          </div>

          <div className="mt-5 flex gap-2">
            {event.status !== "coached" && (
              <button onClick={() => onStatusChange(event.id, "coached")} className="dm-btn-primary !px-3 !py-1.5">
                <CheckCircle2 className="h-4 w-4" /> Mark Resolved
              </button>
            )}
            {event.status !== "dismissed" && (
              <button onClick={() => onStatusChange(event.id, "dismissed")} className="dm-btn-secondary !px-3 !py-1.5">
                <RotateCcw className="h-4 w-4" /> Dismiss
              </button>
            )}
            <button
              onClick={() => setEmailing(true)}
              disabled={!event.has_snapshot}
              title={event.has_snapshot ? undefined : "No snapshot recorded for this event"}
              className="dm-btn-secondary !px-3 !py-1.5"
            >
              <Mail className="h-4 w-4" /> Email
            </button>
            {event.status !== "to_review" && (
              <button onClick={() => onStatusChange(event.id, "to_review")} className="dm-btn-secondary !px-3 !py-1.5">
                <Undo2 className="h-4 w-4" /> Reopen
              </button>
            )}
          </div>

          <div className="mt-6">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-medium text-slate-300">
              <MessageSquare className="h-4 w-4" /> Comment log
            </div>
            <div className="space-y-2">
              {comments.length === 0 && <p className="text-sm text-slate-500">No comments yet.</p>}
              {comments.map((c) => (
                <div key={c.id} className="rounded-lg bg-slate-800/40 px-3 py-2 text-sm">
                  <p className="text-slate-200">{c.text}</p>
                  <p className="mt-1 text-xs text-slate-500">{new Date(c.created_at).toLocaleString()}</p>
                </div>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <input
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddComment()}
                placeholder="Add a coaching note..."
                className="dm-input flex-1"
              />
              <button
                onClick={handleAddComment}
                disabled={posting || !commentText.trim()}
                className="dm-btn-primary !px-3"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {emailing && (
        <EmailIncidentModal event={event} camera={camera} onClose={() => setEmailing(false)} />
      )}
    </div>
  );
}

export default function CoachingWorkbench() {
  const [events, setEvents] = useState<Event[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [tab, setTab] = useState<EventStatus | "all">("to_review");
  const [level, setLevel] = useState<RiskLevel | "all">("all");
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Multi-select for bulk dismiss: Ctrl/Cmd+click toggles a card, Shift+click
  // selects the range from the last clicked card.
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const anchorIdRef = useRef<number | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const loadEvents = useCallback(() => {
    setLoading(true);
    const [min_risk, max_risk] = level === "all" ? [] : LEVEL_RANGE[level];
    const params = { status: tab === "all" ? undefined : tab, min_risk, max_risk };
    api.get<Event[]>("/api/events", { params }).then((res) => {
      setEvents(res.data);
      setLoading(false);
    });
  }, [tab, level]);

  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((res) => setCameras(res.data));
  }, []);

  useEffect(() => {
    loadEvents();
    setSelection(new Set());
    anchorIdRef.current = null;
  }, [loadEvents]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setSelection(new Set());
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const camerasById = useMemo(
    () => Object.fromEntries(cameras.map((c) => [c.id, c])),
    [cameras]
  );

  async function handleStatusChange(id: number, status: EventStatus) {
    await api.patch(`/api/events/${id}`, { status });
    setSelectedId(null);
    loadEvents();
  }

  async function handleRiskChange(id: number, risk_score: number) {
    const { data } = await api.patch<Event>(`/api/events/${id}`, { risk_score });
    setEvents((prev) => prev.map((ev) => (ev.id === id ? data : ev)));
  }

  function handleCardClick(id: number, { shift, toggle }: SelectModifiers) {
    if (shift && anchorIdRef.current != null) {
      const from = events.findIndex((ev) => ev.id === anchorIdRef.current);
      const to = events.findIndex((ev) => ev.id === id);
      if (from !== -1 && to !== -1) {
        const [lo, hi] = from < to ? [from, to] : [to, from];
        setSelection((prev) => {
          const next = toggle ? new Set(prev) : new Set<number>();
          events.slice(lo, hi + 1).forEach((ev) => next.add(ev.id));
          return next;
        });
        return;
      }
    }
    anchorIdRef.current = id;
    if (shift || toggle) {
      setSelection((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      return;
    }
    // Plain click opens the detail view as before.
    setSelectedId(id);
  }

  async function handleBulkDismiss() {
    if (selection.size === 0) return;
    // Dismissing deletes the events (and their snapshots) permanently.
    if (!window.confirm(`Dismiss and permanently delete ${selection.size} event(s)?`)) return;
    setBulkBusy(true);
    try {
      await api.post("/api/events/bulk-status", { ids: [...selection], status: "dismissed" });
      setSelection(new Set());
      anchorIdRef.current = null;
      loadEvents();
    } finally {
      setBulkBusy(false);
    }
  }

  const selectedEvent = events.find((e) => e.id === selectedId);

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Incidents</h2>
          <p className="mt-1 text-sm text-slate-400">
            Review flagged breaches, log coaching conversations, and close them out.
            <span className="text-slate-500"> Ctrl/Shift+click cards to select several.</span>
          </p>
        </div>
        {selection.size > 0 && (
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-sm text-slate-400">{selection.size} selected</span>
            <button onClick={() => setSelection(new Set())} className="dm-btn-secondary !px-3 !py-1.5">
              <X className="h-4 w-4" /> Clear
            </button>
            <button onClick={handleBulkDismiss} disabled={bulkBusy} className="dm-btn-primary !px-3 !py-1.5">
              {bulkBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
              Dismiss {selection.size}
            </button>
          </div>
        )}
      </div>

      <div className="mt-4 flex gap-1 border-b border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.key
                ? "border-b-2 border-apl-sunset text-apl-sunset"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {t.label}
          </button>
        ))}
        <select
          aria-label="Filter by risk level"
          className="dm-input !my-1 !ml-auto !w-auto !px-2 !py-1 text-sm"
          value={level}
          onChange={(e) => setLevel(e.target.value as RiskLevel | "all")}
        >
          <option value="all">All risk levels</option>
          {(Object.keys(LEVEL_RANGE) as RiskLevel[]).map((l) => (
            <option key={l} value={l}>{l} risk</option>
          ))}
        </select>
      </div>

      <div className="mt-4">
        {loading ? (
          <p className="text-sm text-slate-400">Loading events...</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-slate-400">No events in this view.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {events.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                camera={camerasById[event.camera_id ?? -1]}
                selected={selection.has(event.id)}
                onClick={(mods) => handleCardClick(event.id, mods)}
                onDismiss={() => handleStatusChange(event.id, "dismissed")}
              />
            ))}
          </div>
        )}
      </div>

      {selectedEvent && (
        <EventDetail
          event={selectedEvent}
          camera={camerasById[selectedEvent.camera_id ?? -1]}
          onClose={() => setSelectedId(null)}
          onStatusChange={handleStatusChange}
          onRiskChange={handleRiskChange}
        />
      )}
    </div>
  );
}
