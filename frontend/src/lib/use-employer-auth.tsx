"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { User } from "@/lib/types";

/**
 * Route guard for the employer surface (plan §E0).
 *
 * - Still loading  -> render a spinner (`isLoading`)
 * - Signed out     -> /login
 * - Wrong role     -> /dashboard (job-seeker home)
 * - employer/admin -> `ready === true`, page may render
 *
 * ADMIN is allowed through deliberately: the admin console already acts on
 * every tenant, and it lets an admin inspect any employer's view.
 */
export function useEmployerAuth(): {
  user: User | null;
  token: string | null;
  ready: boolean;
  isLoading: boolean;
} {
  const { user, token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (!token) {
      router.push("/login");
      return;
    }
    if (user && user.role !== "employer" && user.role !== "admin") {
      router.push("/dashboard");
    }
  }, [user, token, isLoading, router]);

  const ready =
    !!token && !!user && (user.role === "employer" || user.role === "admin");

  return { user, token, ready, isLoading };
}

/** Shared full-page spinner used while the guard resolves. */
export function EmployerLoading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
    </div>
  );
}
