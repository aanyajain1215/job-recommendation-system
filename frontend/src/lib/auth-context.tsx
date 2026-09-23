"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { AuthResponse, LoginPayload, RegisterPayload, User } from "./types";
import { getBrowserApiBaseUrl } from "./api";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  token: string | null;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const ACCESS_TOKEN_KEY = "jobrec_access_token";
const REFRESH_TOKEN_KEY = "jobrec_refresh_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchCurrentUser = useCallback(async (authToken: string) => {
    try {
      const apiBase = getBrowserApiBaseUrl();
      const res = await fetch(`${apiBase}/api/v1/auth/me`, {
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
      });

      if (res.ok) {
        const userData: User = await res.json();
        setUser(userData);
        setToken(authToken);
      } else {
        // Token invalid or expired
        localStorage.removeItem(ACCESS_TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
        setUser(null);
        setToken(null);
      }
    } catch {
      setUser(null);
      setToken(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const savedToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    if (savedToken) {
      fetchCurrentUser(savedToken);
    } else {
      setIsLoading(false);
    }
  }, [fetchCurrentUser]);

  const login = async (payload: LoginPayload) => {
    setIsLoading(true);
    const apiBase = getBrowserApiBaseUrl();
    const res = await fetch(`${apiBase}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      setIsLoading(false);
      const errorData = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(errorData.detail || "Invalid email or password.");
    }

    const data: AuthResponse = await res.json();
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
    setIsLoading(false);
  };

  const register = async (payload: RegisterPayload) => {
    setIsLoading(true);
    const apiBase = getBrowserApiBaseUrl();
    const res = await fetch(`${apiBase}/api/v1/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      setIsLoading(false);
      const errorData = await res.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(errorData.detail || "Registration failed. Please check your inputs.");
    }

    const data: AuthResponse = await res.json();
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
    setIsLoading(false);
  };

  const logout = () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    setToken(null);
    setUser(null);
  };

  const refreshUser = async () => {
    const currentToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    if (currentToken) {
      await fetchCurrentUser(currentToken);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        token,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
