import { useEffect, useRef, useState } from "react";
import { Loader2, VideoOff } from "lucide-react";
import { api } from "../lib/api";
import { token } from "../lib/theme";
import type { ClipOverlay } from "../types";

// Plays an incident's raw clip and draws the detection boxes from its JSON overlay on top
// (ADR 0008: the clip itself stays untouched as evidence). Both endpoints need the login
// token, so they're fetched via axios and the video gets a blob: URL.
export default function EventClip({ eventId }: { eventId: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<ClipOverlay | null>(null);
  const [failed, setFailed] = useState(false);
  const [showBoxes, setShowBoxes] = useState(true);

  useEffect(() => {
    let url: string | null = null;
    setSrc(null);
    setFailed(false);
    Promise.all([
      api.get(`/api/events/${eventId}/clip`, { responseType: "blob" }),
      api.get<ClipOverlay>(`/api/events/${eventId}/clip-overlay`),
    ])
      .then(([clip, ov]) => {
        url = URL.createObjectURL(clip.data as Blob);
        setSrc(url);
        setOverlay(ov.data);
      })
      .catch(() => setFailed(true));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [eventId]);

  // Redraw the boxes of the overlay frame nearest the video's current time.
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !overlay) return;
    let raf = 0;
    const draw = () => {
      const ctx = canvas.getContext("2d");
      if (ctx) {
        canvas.width = overlay.width;
        canvas.height = overlay.height;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (showBoxes && overlay.frames.length) {
          const t = video.currentTime;
          let frame = overlay.frames[0];
          for (const f of overlay.frames) {
            if (f.t <= t + 0.001) frame = f;
            else break;
          }
          ctx.lineWidth = 2;
          ctx.font = "bold 12px Inter, system-ui, sans-serif";
          for (const b of frame.boxes) {
            const [x1, y1, x2, y2] = b.xyxy;
            const color = token(b.threat ? "critical" : "accent");
            ctx.strokeStyle = color;
            ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
            const label = `#${b.id} ${b.cls}${b.conf != null ? ` ${b.conf.toFixed(2)}` : ""}`;
            const w = ctx.measureText(label).width + 6;
            ctx.fillStyle = color;
            ctx.fillRect(x1, Math.max(y1 - 16, 0), w, 16);
            ctx.fillStyle = b.threat ? "#fff" : "#000"; // label text on amber / red, as on the live stream
            ctx.fillText(label, x1 + 3, Math.max(y1 - 4, 12));
          }
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [overlay, showBoxes, src]);

  if (failed) {
    return (
      <div className="flex aspect-video items-center justify-center rounded bg-panel-2 text-muted">
        <VideoOff className="h-8 w-8" />
      </div>
    );
  }
  if (!src || !overlay) {
    return (
      <div className="dm-skeleton flex aspect-video items-center justify-center text-muted">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="relative aspect-video overflow-hidden rounded bg-black">
        <video ref={videoRef} src={src} controls className="h-full w-full object-contain" />
        <canvas
          ref={canvasRef}
          className="pointer-events-none absolute inset-0 h-full w-full object-contain"
          style={{ objectFit: "contain" }}
        />
      </div>
      <label className="flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
        Show detection boxes (drawn on top; the stored clip has none)
      </label>
    </div>
  );
}
