"use client";

import Link from "next/link";
import { BarChart3, FileText, Lightbulb, UserSearch, Users, Wand2 } from "lucide-react";

export type PostingTabKey =
  | "overview"
  | "applicants"
  | "talent"
  | "insights"
  | "whatif"
  | "performance";

interface TabDef {
  key: PostingTabKey;
  label: string;
  href?: string; // absent = not built yet (shown disabled)
  icon: React.ReactNode;
}

/**
 * Shared tab bar for a posting's sub-pages (plan §E1).
 *
 * Only Overview and Applicants are live; later phases flip `href` on the
 * remaining tabs as they land (E2 talent, E3 insights, E4 performance) —
 * they render disabled with a "soon" pill rather than as dead links.
 */
export function PostingTabs({ jobId, active }: { jobId: string; active: PostingTabKey }) {
  const tabs: TabDef[] = [
    { key: "overview", label: "Overview", href: `/hiring/postings/${jobId}`, icon: <FileText className="h-4 w-4" /> },
    { key: "applicants", label: "Applicants", href: `/hiring/postings/${jobId}/applicants`, icon: <Users className="h-4 w-4" /> },
    { key: "talent", label: "Talent", href: `/hiring/postings/${jobId}/talent`, icon: <UserSearch className="h-4 w-4" /> },
    { key: "insights", label: "Insights", href: `/hiring/postings/${jobId}/insights`, icon: <Lightbulb className="h-4 w-4" /> },
    { key: "whatif", label: "What-If", href: `/hiring/postings/${jobId}/whatif`, icon: <Wand2 className="h-4 w-4" /> },
    { key: "performance", label: "Performance", href: `/hiring/postings/${jobId}/performance`, icon: <BarChart3 className="h-4 w-4" /> },
  ];

  return (
    <nav className="flex flex-wrap gap-1 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-1">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        if (tab.href) {
          return (
            <Link
              key={tab.key}
              href={tab.href}
              aria-current={isActive ? "page" : undefined}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-teal-500/15 text-teal-300 ring-1 ring-inset ring-teal-500/30"
                  : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200"
              }`}
            >
              {tab.icon}
              {tab.label}
            </Link>
          );
        }
        return (
          <span
            key={tab.key}
            title="Arrives in a later phase"
            className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium text-zinc-600"
          >
            {tab.icon}
            {tab.label}
            <span className="rounded-full bg-zinc-800 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-300">
              soon
            </span>
          </span>
        );
      })}
    </nav>
  );
}
