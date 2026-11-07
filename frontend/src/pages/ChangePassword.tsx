import { useState, type FormEvent } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import TiamLogo from "../components/TiamLogo";

// Shown instead of the app while the user must change a one-time password (the backend
// refuses every other call until then).
export default function ChangePassword() {
  const { user, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError("The new passwords don't match.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/api/auth/change-password", { current_password: current, new_password: next });
      window.location.assign("/"); // reload so /api/auth/me returns the cleared flag
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to change password");
      setSaving(false);
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-bg p-4 text-fg">
      <form onSubmit={handleSubmit} className="dm-card w-full max-w-sm space-y-4 p-8">
        <TiamLogo className="h-7" />
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <KeyRound className="h-4 w-4 text-accent" /> Set a new password
          </h1>
          <p className="text-sm text-muted">
            {user?.username} is using a one-time password. Choose a new one (at least 10 characters) to continue.
          </p>
        </div>
        <label className="block text-sm">
          <span className="dm-label">Current (one-time) password</span>
          <input type="password" required autoComplete="current-password" value={current}
            onChange={(e) => setCurrent(e.target.value)} className="dm-input" />
        </label>
        <label className="block text-sm">
          <span className="dm-label">New password</span>
          <input type="password" required minLength={10} autoComplete="new-password" value={next}
            onChange={(e) => setNext(e.target.value)} className="dm-input" />
        </label>
        <label className="block text-sm">
          <span className="dm-label">Confirm new password</span>
          <input type="password" required minLength={10} autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} className="dm-input" />
        </label>
        {error && <p className="text-sm text-critical" role="alert">{error}</p>}
        <div className="flex items-center justify-between">
          <button type="button" onClick={logout} className="text-sm text-muted hover:text-fg">Sign out</button>
          <button type="submit" disabled={saving} className="dm-btn-primary">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />} Save password
          </button>
        </div>
      </form>
    </div>
  );
}
