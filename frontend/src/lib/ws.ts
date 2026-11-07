import { TOKEN_STORAGE_KEY } from "./api";
import { WS_BASE_URL } from "./config";

/** Builds a WebSocket URL for `path`, attaching the stored session token as
 * a query param -- WebSocket clients can't set an Authorization header, so
 * the backend accepts the token this way instead for /ws/* routes. */
export function buildWsUrl(path: string): string {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${WS_BASE_URL}${path}${query}`;
}
