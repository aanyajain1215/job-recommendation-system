"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  Bot,
  Briefcase,
  Bookmark,
  Building2,
  Compass,
  FileText,
  GitBranch,
  LayoutDashboard,
  LogOut,
  Menu,
  PlusCircle,
  Route,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
  X,
} from "lucide-react";

function navLinkClass(active: boolean, tone: "teal" | "rose" = "teal") {
  if (active) {
    const activeColor = tone === "rose" ? "text-rose-400" : "text-teal-500";
    return `inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-zinc-900 px-2.5 text-[13px] font-semibold ${activeColor} shadow-xs ring-1 ring-zinc-800/80 transition-colors`;
  }
  return "inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 text-[13px] font-medium text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-100 transition-colors";
}

export function Navbar() {
  const pathname = usePathname();
  const { user, logout, isLoading } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const getRoleBadge = (role: string) => {
    switch (role) {
      case "employer":
        return (
          <span className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-indigo-500/10 px-2.5 text-[11px] font-semibold text-indigo-400 ring-1 ring-inset ring-indigo-500/30">
            <Building2 className="h-3 w-3 shrink-0" />
            Employer
          </span>
        );
      case "admin":
        return (
          <span className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-rose-500/10 px-2.5 text-[11px] font-semibold text-rose-400 ring-1 ring-inset ring-rose-500/30">
            Admin
          </span>
        );
      default:
        return (
          <span className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full bg-teal-500/10 px-2.5 text-[11px] font-semibold text-teal-400 ring-1 ring-inset ring-teal-500/30">
            <Sparkles className="h-3 w-3 shrink-0" />
            Job Seeker
          </span>
        );
    }
  };

  const renderNavLinks = (mobile = false) => {
    const linkExtra = mobile ? " w-full justify-start h-10 px-3 text-sm" : "";

    if (user?.role === "employer") {
      return (
        <>
          <Link href="/hiring" className={`${navLinkClass(pathname === "/hiring")}${linkExtra}`}>
            <LayoutDashboard className="h-4 w-4 shrink-0" />
            Hiring
          </Link>
          <Link
            href="/hiring/postings"
            className={`${navLinkClass(pathname.startsWith("/hiring/postings"))}${linkExtra}`}
          >
            <FileText className="h-4 w-4 shrink-0" />
            Postings
          </Link>
          <Link
            href="/hiring/company"
            className={`${navLinkClass(pathname === "/hiring/company")}${linkExtra}`}
          >
            <Building2 className="h-4 w-4 shrink-0" />
            Company
          </Link>
          <Link
            href="/jobs/new"
            className={`inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-teal-500 px-3 text-[13px] font-semibold text-zinc-950 shadow-sm shadow-teal-500/20 hover:bg-teal-400 active:scale-[0.98] transition-all ${
              mobile ? "w-full justify-center h-10 mt-1" : "ml-1.5"
            }`}
          >
            <PlusCircle className="h-4 w-4 shrink-0" />
            Post a job
          </Link>
        </>
      );
    }

    if (user?.role === "job_seeker") {
      return (
        <>
          <Link href="/jobs" className={`${navLinkClass(pathname.startsWith("/jobs"))}${linkExtra}`}>
            <Compass className="h-3.5 w-3.5 shrink-0" />
            Find Jobs
          </Link>
          <Link
            href="/recommendations"
            className={`${navLinkClass(pathname === "/recommendations")}${linkExtra}`}
          >
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-teal-400" />
            AI Matches
          </Link>
          <Link href="/copilot" className={`${navLinkClass(pathname === "/copilot")}${linkExtra}`}>
            <Bot className="h-3.5 w-3.5 shrink-0 text-teal-400" />
            Copilot
          </Link>
          <Link href="/careers" className={`${navLinkClass(pathname === "/careers")}${linkExtra}`}>
            <Route className="h-3.5 w-3.5 shrink-0" />
            Careers
          </Link>
          <Link href="/simulator" className={`${navLinkClass(pathname === "/simulator")}${linkExtra}`}>
            <GitBranch className="h-3.5 w-3.5 shrink-0" />
            What-If
          </Link>
          <Link href="/saved" className={`${navLinkClass(pathname === "/saved")}${linkExtra}`}>
            <Bookmark className="h-3.5 w-3.5 shrink-0" />
            Saved
          </Link>
          <Link href="/profile" className={`${navLinkClass(pathname === "/profile")}${linkExtra}`}>
            <UserIcon className="h-3.5 w-3.5 shrink-0" />
            Profile
          </Link>
        </>
      );
    }

    return (
      <>
        <Link href="/jobs" className={`${navLinkClass(pathname.startsWith("/jobs"))}${linkExtra}`}>
          <Compass className="h-3.5 w-3.5 shrink-0" />
          Find Jobs
        </Link>
        {user?.role === "admin" && (
          <Link href="/admin" className={`${navLinkClass(pathname === "/admin", "rose")}${linkExtra}`}>
            <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-rose-400" />
            Admin
          </Link>
        )}
      </>
    );
  };

  return (
    <header className="sticky top-0 z-40 w-full border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        {/* Left: Brand + Desktop Navigation */}
        <div className="flex min-w-0 items-center gap-4 xl:gap-6">
          <Link href="/" className="flex shrink-0 items-center gap-2.5 group whitespace-nowrap">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950 font-bold shadow-md shadow-teal-500/10 transition-transform group-hover:scale-105">
              <Briefcase className="h-5 w-5 text-zinc-950" />
            </div>
            <span className="flex items-center gap-1.5 text-lg font-bold tracking-tight text-zinc-100 whitespace-nowrap">
              JobRec
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse" />
            </span>
          </Link>

          <nav className="hidden lg:flex items-center gap-0.5">{renderNavLinks(false)}</nav>
        </div>

        {/* Right: Auth status + Mobile Toggle */}
        <div className="flex shrink-0 items-center gap-2">
          {isLoading ? (
            <div className="h-8 w-28 animate-pulse rounded-lg bg-zinc-800" />
          ) : user ? (
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex items-center">{getRoleBadge(user.role)}</div>

              <Link
                href={user.role === "employer" ? "/hiring" : "/dashboard"}
                className="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border border-zinc-800 bg-zinc-900/80 px-3 text-xs font-medium text-zinc-200 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
              >
                <UserIcon className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                <span className="max-w-[120px] truncate">
                  {user.profile?.first_name ? user.profile.first_name : user.email.split("@")[0]}
                </span>
              </Link>

              <button
                onClick={logout}
                title="Sign Out"
                aria-label="Sign Out"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100 hover:border-zinc-700 transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link
                href="/login"
                className="inline-flex h-8 shrink-0 items-center whitespace-nowrap rounded-lg px-3 text-sm font-medium text-zinc-300 hover:bg-zinc-900/60 hover:text-zinc-100 transition-colors"
              >
                Sign In
              </Link>
              <Link
                href="/register"
                className="inline-flex h-8 shrink-0 items-center justify-center whitespace-nowrap rounded-lg bg-teal-500 px-3.5 text-sm font-semibold text-zinc-950 shadow-sm shadow-teal-500/20 hover:bg-teal-400 active:scale-[0.98] transition-all"
              >
                Get Started
              </Link>
            </div>
          )}

          <button
            type="button"
            onClick={() => setMobileOpen((o) => !o)}
            aria-label="Toggle navigation menu"
            aria-expanded={mobileOpen}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900/70 text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 lg:hidden"
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Mobile / Tablet Drawer */}
      {mobileOpen && (
        <div className="border-t border-zinc-800/80 bg-zinc-950 px-4 py-3 lg:hidden">
          {user && <div className="mb-2.5 sm:hidden">{getRoleBadge(user.role)}</div>}
          <nav className="flex flex-col gap-1">{renderNavLinks(true)}</nav>
        </div>
      )}
    </header>
  );
}
