// Reads a design token (CSS variable from index.css) for code that can't use Tailwind classes:
// canvas drawing and Recharts props.
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}
