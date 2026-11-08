import type { VlmStatus, VlmVerdict } from "../types";

// AI verification state of an incident (spec 6.6): ✓ Confirmed 0.91 · ◐ Uncertain · ✕ Rejected ·
// … Verifying · Unverified. Nothing is shown for incidents that were never sent to the AI.
export default function VlmChip({
  status,
  verdict,
  confidence,
  className = "",
}: {
  status?: VlmStatus | null;
  verdict?: VlmVerdict | null;
  confidence?: number | null;
  className?: string;
}) {
  if (!status || status === "none") return null;
  let text: string;
  let tone: string;
  if (status === "pending") {
    text = "… Verifying";
    tone = "dm-pill-slate";
  } else if (status === "done" && verdict === "confirmed") {
    text = `✓ Confirmed${confidence != null ? ` ${confidence.toFixed(2)}` : ""}`;
    tone = "dm-pill-red";
  } else if (status === "done" && verdict === "rejected") {
    text = "✕ Rejected";
    tone = "dm-pill-emerald";
  } else if (status === "done" && verdict === "uncertain") {
    text = "◐ Uncertain";
    tone = "dm-pill-amber";
  } else {
    text = "Unverified";
    tone = "dm-pill-slate";
  }
  return (
    <span className={`${tone} ${className}`} title="AI verification">
      AI {text}
    </span>
  );
}
