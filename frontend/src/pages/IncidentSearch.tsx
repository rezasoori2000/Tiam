import { useMemo, useState, type FormEvent } from "react";
import { Clock, ImageOff, Loader2, Search } from "lucide-react";
import { api } from "../lib/api";
import { EventDetail, EventSnapshot, riskColor, riskLevel, timeAgo } from "./CoachingWorkbench";
import type { Camera, Event, EventStatus } from "../types";

const EXAMPLES = [
  "Camera 2, speeding last week",
  "exclusion zone breach yesterday",
];

function ResultCard({
  event,
  camera,
  onClick,
}: {
  event: Event;
  camera?: Camera;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="dm-card flex flex-col overflow-hidden text-left transition-colors hover:border-slate-700"
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
        <span
          className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-xs font-bold text-fg ${riskColor(
            event.risk_score
          )}`}
        >
          {riskLevel(event.risk_score)} · {event.risk_score}
        </span>
      </div>
      <div className="space-y-1 p-3">
        <div className="line-clamp-1 text-sm font-medium text-slate-100">{event.policy_type}</div>
        <div className="text-xs text-slate-500">
          {camera?.name ?? `Camera ${event.camera_id}`} &middot; {event.zone_name}
        </div>
        <div className="flex items-center gap-1 pt-1 text-xs text-slate-500">
          <Clock className="h-3 w-3" /> {timeAgo(event.timestamp)} &middot;{" "}
          {new Date(event.timestamp).toLocaleString()}
        </div>
      </div>
    </button>
  );
}

export default function IncidentSearch() {
  const [query, setQuery] = useState("");
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [results, setResults] = useState<Event[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useMemo(() => {
    api.get<Camera[]>("/api/cameras").then((res) => setCameras(res.data));
  }, []);

  const camerasById = useMemo(
    () => Object.fromEntries(cameras.map((c) => [c.id, c])),
    [cameras]
  );

  async function runSearch(q: string) {
    if (!q.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const res = await api.get<Event[]>("/api/incidents/search", { params: { q } });
      setResults(res.data);
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    runSearch(query);
  }

  async function handleStatusChange(id: number, status: EventStatus) {
    await api.patch(`/api/events/${id}`, { status });
    setSelectedId(null);
    runSearch(query);
  }

  async function handleRiskChange(id: number, risk_score: number) {
    const { data } = await api.patch<Event>(`/api/events/${id}`, { risk_score });
    setResults((prev) => prev.map((ev) => (ev.id === id ? data : ev)));
  }

  const selectedEvent = results.find((e) => e.id === selectedId);

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100">Incident Search</h2>
      <p className="mt-1 text-sm text-slate-400">
        Ask about past incidents in plain English -- camera, zone, rule type and date/time are
        matched against existing events. Returns a list of matching incidents; no generated
        answer.
      </p>

      <form onSubmit={handleSubmit} className="mt-4 flex gap-2">
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Camera 2, show me speeding incidents last week"
          className="dm-input flex-1"
        />
        <button type="submit" disabled={loading || !query.trim()} className="dm-btn-primary">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Search
        </button>
      </form>

      <div className="mt-2 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setQuery(ex);
              runSearch(ex);
            }}
            className="dm-pill-slate"
          >
            {ex}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {!searched ? (
          <p className="text-sm text-slate-400">Try a search above, or pick an example.</p>
        ) : loading ? (
          <p className="text-sm text-slate-400">Searching...</p>
        ) : results.length === 0 ? (
          <p className="text-sm text-slate-400">No matching incidents found.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {results.map((event) => (
              <ResultCard
                key={event.id}
                event={event}
                camera={camerasById[event.camera_id ?? -1]}
                onClick={() => setSelectedId(event.id)}
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
