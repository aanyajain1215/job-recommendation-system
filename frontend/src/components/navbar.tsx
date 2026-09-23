"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Briefcase, Building2, Compass, GitBranch, LogOut, PlusCircle, Route, Sparkles, User as UserIcon } from "lucide-react";

export function Navbar() {
  const pathname = usePathname();
  const { user, logout, isLoading } = useAuth();

  const getRoleBadge = (role: string) => {
    switch (role) {
      case "employer":
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2.5 py-0.5 text-xs font-medium text-indigo-400 ring-1 ring-inset ring-indigo-500/30">
            <Building2 className="h-3 w-3" />
            Employer
          </span>
        );
      case "admin":
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2.5 py-0.5 text-xs font-medium text-rose-400 ring-1 ring-inset ring-rose-500/30">
            Admin
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-xs font-medium text-teal-300 ring-1 ring-inset ring-teal-500/30">
            <Sparkles className="h-3 w-3" />
            Job Seeker
          </span>
        );
    }
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950 font-bold shadow-md shadow-teal-500/10 transition-transform group-hover:scale-105">
              <Briefcase className="h-5 w-5 text-zinc-950" />
            </div>
            <div className="flex flex-col">
              <span className="text-lg font-bold tracking-tight text-white flex items-center gap-1.5">
                JobRec
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse" />
              </span>
            </div>
          </Link>

          {/* Nav items */}
          <nav className="hidden md:flex items-center gap-1">
            <Link
              href="/jobs"
              className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                pathname === "/jobs"
                  ? "text-teal-400 bg-zinc-900/60"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
              }`}
            >
              <Compass className="h-4 w-4" />
              Find Jobs
            </Link>

            {user?.role === "employer" && (
              <>
                <Link
                  href="/jobs/new"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/jobs/new"
                      ? "text-indigo-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <PlusCircle className="h-4 w-4" />
                  Post a Job
                </Link>
                <Link
                  href="/dashboard"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/dashboard"
                      ? "text-indigo-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <Building2 className="h-4 w-4" />
                  Employer Hub
                </Link>
              </>
            )}

            {user?.role === "job_seeker" && (
              <>
                <Link
                  href="/recommendations"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/recommendations"
                      ? "text-teal-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <Sparkles className="h-4 w-4 text-teal-400" />
                  AI Matches
                </Link>
                <Link
                  href="/careers"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/careers"
                      ? "text-teal-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <Route className="h-4 w-4" />
                  Careers
                </Link>
                <Link
                  href="/simulator"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/simulator"
                      ? "text-teal-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <GitBranch className="h-4 w-4" />
                  What-If
                </Link>
                <Link
                  href="/profile"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/profile"
                      ? "text-teal-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <UserIcon className="h-4 w-4" />
                  Profile & Resume
                </Link>
                <Link
                  href="/dashboard"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    pathname === "/dashboard"
                      ? "text-teal-400 bg-zinc-900/60"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/40"
                  }`}
                >
                  <Compass className="h-4 w-4" />
                  Dashboard
                </Link>
              </>
            )}
          </nav>
        </div>

        {/* Right side Auth status */}
        <div className="flex items-center gap-3">
          {isLoading ? (
            <div className="h-8 w-24 animate-pulse rounded-md bg-zinc-800" />
          ) : user ? (
            <div className="flex items-center gap-3">
              {getRoleBadge(user.role)}

              <Link
                href="/dashboard"
                className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-1.5 text-xs text-zinc-300 hover:border-zinc-700 hover:text-white transition-colors"
              >
                <UserIcon className="h-3.5 w-3.5 text-zinc-400" />
                <span className="max-w-[140px] truncate">
                  {user.profile?.first_name
                    ? `${user.profile.first_name}`
                    : user.email.split("@")[0]}
                </span>
              </Link>

              <button
                onClick={logout}
                title="Sign Out"
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200 hover:border-zinc-700 transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2.5">
              <Link
                href="/login"
                className="px-3.5 py-1.5 text-sm font-medium text-zinc-300 hover:text-white transition-colors"
              >
                Sign In
              </Link>
              <Link
                href="/register"
                className="inline-flex items-center justify-center rounded-lg bg-teal-500 px-4 py-1.5 text-sm font-medium text-zinc-950 shadow-sm shadow-teal-500/20 hover:bg-teal-400 active:scale-[0.98] transition-all"
              >
                Get Started
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
