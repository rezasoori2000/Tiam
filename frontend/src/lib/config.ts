// Dev: the Vite dev server (:5173) talks to a separately-run backend on :8000.
// Release build: the backend serves this SPA itself, so default to whatever
// origin the page was loaded from (e.g. http://APLCHCHCAM02:8000).
const DEFAULT_HTTP_BASE = import.meta.env.DEV
  ? "http://localhost:8000"
  : window.location.origin;

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_HTTP_BASE;

export const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ?? DEFAULT_HTTP_BASE.replace(/^http/, "ws");
