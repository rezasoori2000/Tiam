import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { Role, User, UserCreatePayload } from "../types";

interface FormState {
  username: string;
  password: string;
  role_id: string;
}

const INITIAL_FORM: FormState = { username: "", password: "", role_id: "" };

export default function UserManagement() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [usersRes, rolesRes] = await Promise.all([
      api.get<User[]>("/api/users"),
      api.get<Role[]>("/api/roles"),
    ]);
    setUsers(usersRes.data);
    setRoles(rolesRes.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function roleName(roleId: number): string {
    return roles.find((r) => r.id === roleId)?.name ?? "Unknown role";
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!form.role_id) {
      setError("Select a role -- create one first in Role Management if none exist.");
      return;
    }
    setSubmitting(true);
    try {
      const payload: UserCreatePayload = {
        username: form.username,
        password: form.password,
        role_id: Number(form.role_id),
      };
      await api.post("/api/users", payload);
      setForm(INITIAL_FORM);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to create user");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this user?")) return;
    try {
      await api.delete(`/api/users/${id}`);
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? "Failed to delete user");
    }
  }

  async function handleResetPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!resetTarget) return;
    setResetError(null);
    try {
      await api.post(`/api/users/${resetTarget.id}/reset-password`, {
        new_password: resetPassword,
      });
      setResetTarget(null);
      setResetPassword("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setResetError(typeof detail === "string" ? detail : "Failed to reset password");
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">User Management</h2>
        <p className="mt-1 text-sm text-slate-400">
          Add users and assign them a role. If no role exists yet, create one first in Role
          Management.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="dm-card space-y-4 p-5">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">
            <span className="dm-label">Username</span>
            <input
              required
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              className="dm-input"
            />
          </label>
          <label className="text-sm">
            <span className="dm-label">Password</span>
            <input
              required
              type="password"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              className="dm-input"
            />
          </label>
          <label className="col-span-2 text-sm">
            <span className="dm-label">Role</span>
            <select
              value={form.role_id}
              onChange={(e) => setForm((f) => ({ ...f, role_id: e.target.value }))}
              className="dm-input"
            >
              <option value="">
                {roles.length === 0 ? "No roles yet -- create one in Role Management" : "Select a role"}
              </option>
              {roles
                .filter((r) => !r.is_system)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
            </select>
          </label>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button type="submit" disabled={submitting || roles.length === 0} className="dm-btn-primary">
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Add User
        </button>
      </form>

      <div className="dm-card">
        {loading ? (
          <div className="p-6 text-sm text-slate-400">Loading users...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-3 font-medium">Username</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-100">
                      {u.username}
                      {u.is_system && <span className="dm-pill-slate ml-2">Built-in</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400">{roleName(u.role_id)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => {
                          setResetTarget(u);
                          setResetPassword("");
                          setResetError(null);
                        }}
                        className="text-slate-500 hover:text-apl-sunset"
                        title="Edit / reset password"
                      >
                        <KeyRound className="h-4 w-4" />
                      </button>
                      {!u.is_system && (
                        <button
                          onClick={() => handleDelete(u.id)}
                          className="text-slate-500 hover:text-red-400"
                          title="Delete user"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {resetTarget && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60">
          <form
            onSubmit={handleResetPassword}
            className="dm-card w-full max-w-sm space-y-4 p-5"
          >
            <h3 className="text-sm font-semibold text-slate-100">
              Reset password for {resetTarget.username}
            </h3>
            <label className="block text-sm">
              <span className="dm-label">New password</span>
              <input
                required
                autoFocus
                type="password"
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
                className="dm-input"
              />
            </label>
            {resetError && <p className="text-sm text-red-400">{resetError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setResetTarget(null)}
                className="dm-btn-secondary"
              >
                Cancel
              </button>
              <button type="submit" className="dm-btn-primary">
                Save
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
