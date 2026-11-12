import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, clearTokens, setActiveOrg, setTokens } from "./api";
import type { User } from "./types";

type AuthValue = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithOtp: (email: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  async function refreshUser() {
    const next = await api<User>("/api/v1/auth/me/");
    setUser(next);
  }

  useEffect(() => {
    refreshUser()
      .catch(() => {
        clearTokens();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      refreshUser,
      async login(email, password) {
        const data = await api<{ access: string; refresh: string; user: User }>("/api/v1/auth/login/", {
          method: "POST",
          json: { email, password },
        });
        setTokens(data.access, data.refresh);
        client.clear();
        setUser(data.user);
      },
      async loginWithOtp(email, code) {
        const data = await api<{ access: string; refresh: string; user: User }>("/api/v1/auth/otp/verify/", {
          method: "POST",
          json: { email, code },
        });
        setTokens(data.access, data.refresh);
        client.clear();
        setUser(data.user);
      },
      async logout() {
        const refresh = sessionStorage.getItem("sable.refresh");
        try {
          await api("/api/v1/auth/logout/", { method: "POST", json: { refresh } });
        } catch {
          /* local sign-out still clears the desk session */
        }
        clearTokens();
        setActiveOrg("");
        client.clear();
        setUser(null);
      },
    }),
    [user, loading, client],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}

export function roleOf(user: User | null) {
  if (!user) return "";
  if (user.is_platform_admin && !user.membership) return "platform_admin";
  return user.membership?.role ?? "";
}

export function isAgency(user: User | null) {
  const role = roleOf(user);
  return !!user?.is_platform_admin || role === "agency_admin" || role === "recruiter";
}

export function isAdmin(user: User | null) {
  return !!user?.is_platform_admin || roleOf(user) === "agency_admin";
}

export function isPlatform(user: User | null) {
  return !!user?.is_platform_admin;
}
