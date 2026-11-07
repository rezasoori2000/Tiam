import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, TOKEN_STORAGE_KEY } from "../lib/api";
import type { LoginResponse, Role, User } from "../types";

interface AuthContextValue {
  user: User | null;
  role: Role | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .get<{ user: User; role: Role }>("/api/auth/me")
      .then((res) => {
        setUser(res.data.user);
        setRole(res.data.role);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<LoginResponse>("/api/auth/login", { username, password });
    localStorage.setItem(TOKEN_STORAGE_KEY, res.data.token);
    setUser(res.data.user);
    setRole(res.data.role);
  }, []);

  const logout = useCallback(() => {
    api.post("/api/auth/logout").catch(() => {});
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setUser(null);
    setRole(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, role, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
