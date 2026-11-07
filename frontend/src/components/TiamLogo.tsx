// Placeholder "Tiam" mark: a camera lens (ring + iris) in the accent colour, wordmark in text colour.
export default function TiamLogo({ className = "h-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 112 28" className={`w-auto ${className}`} role="img" aria-label="Tiam">
      <circle cx="14" cy="14" r="11" fill="none" stroke="var(--accent)" strokeWidth="3" />
      <circle cx="14" cy="14" r="4.5" fill="var(--accent)" />
      <circle cx="16" cy="12" r="1.5" fill="var(--bg)" />
      <text
        x="34"
        y="20.5"
        fill="var(--text)"
        fontFamily="Inter, system-ui, sans-serif"
        fontSize="19"
        fontWeight="700"
        letterSpacing="3"
      >
        TIAM
      </text>
    </svg>
  );
}
