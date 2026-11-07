import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import TiamLogo from "../components/TiamLogo";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex h-screen w-screen items-center justify-center overflow-hidden bg-apl-midnight text-slate-100">
      {/* Thin geometric line/diamond accents, transparent over the dark background --
          the brand guide's "Brand style" / "Thank you" pages (p.8, p.16) use this as a
          recurring decorative motif on marketing-facing surfaces. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-40 -top-40 h-[36rem] w-[36rem] rotate-45 rounded-[4rem] border border-line"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-56 -left-56 h-[44rem] w-[44rem] rounded-full border border-line"
      />

      <form
        onSubmit={handleSubmit}
        className="dm-card relative w-full max-w-sm space-y-5 p-8"
      >
        <div className="space-y-4">
          <TiamLogo className="h-7" />
          <div>
            <h1 className="font-display text-2xl font-light text-slate-50">Security Monitor</h1>
            <p className="text-sm text-slate-400">Sign in to continue</p>
          </div>
        </div>

        <label className="block text-sm">
          <span className="dm-label">Username</span>
          <input
            required
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="dm-input"
          />
        </label>
        <label className="block text-sm">
          <span className="dm-label">Password</span>
          <input
            required
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="dm-input"
          />
        </label>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button type="submit" disabled={submitting} className="dm-btn-primary w-full justify-center">
          {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
          Sign In
        </button>
      </form>
    </div>
  );
}
