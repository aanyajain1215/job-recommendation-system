"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getMyApplications, getMyApplicationStats, updateApplication, getApplicationHistory } from "@/lib/api";
import { ApplicationItem, ApplicationStats, ApplicationStatus, ApplicationStatusHistoryItem } from "@/lib/types";
import {
  AlertCircle,
  ArrowRight,
  Award,
  CheckCircle,
  Clock,
  ExternalLink,
  Eye,
  ListChecks,
  TrendingUp,
  XCircle,
  History,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

const PIPELINE_STATUSES: ApplicationStatus[] = [
  "applied",
  "viewed",
  "shortlisted",
  "interview",
  "rejected",
  "offer",
  "hired",
];

const STATUS_STYLES: Record<string, string> = {
  applied: "bg-cyan-500/10 text-cyan-300 ring-cyan-500/30",
  viewed: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  shortlisted: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  interview: "bg-indigo-500/10 text-indigo-300 ring-indigo-500/30",
  rejected: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  offer: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  hired: "bg-teal-500/15 text-teal-200 ring-teal-400/40",
  saved: "bg-teal-500/10 text-teal-300 ring-teal-500/30",
};

export default function TrackerPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [apps, setApps] = useState<ApplicationItem[]>([]);
  const [stats, setStats] = useState<ApplicationStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState<Record<string, boolean>>({});
  const [historyData, setHistoryData] = useState<Record<string, ApplicationStatusHistoryItem[]>>({});
  const [loadingHistory, setLoadingHistory] = useState<Record<string, boolean>>({});

  const toggleHistory = async (appId: string) => {
    if (historyOpen[appId]) {
      setHistoryOpen((prev) => ({ ...prev, [appId]: false }));
      return;
    }
    setHistoryOpen((prev) => ({ ...prev, [appId]: true }));
    if (!historyData[appId] && token) {
      setLoadingHistory((prev) => ({ ...prev, [appId]: true }));
      try {
        const items = await getApplicationHistory(appId, token);
        setHistoryData((prev) => ({ ...prev, [appId]: items }));
      } catch {
        // ignore
      } finally {
        setLoadingHistory((prev) => ({ ...prev, [appId]: false }));
      }
    }
  };

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      const [list, s] = await Promise.all([
        getMyApplications(token),
        getMyApplicationStats(token),
      ]);
      // Saved-later rows live on /saved; this page is the pipeline.
      setApps(list.filter((a) => a.status !== "saved"));
      setStats(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tracker");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (token && user) load();
  }, [user, token, authLoading, router, load]);

  const handleStatusChange = async (appId: string, status: ApplicationStatus) => {
    if (!token) return;
    setSavingId(appId);
    try {
      await updateApplication(appId, status, token);
      setApps((prev) =>
        prev.map((a) => (a.id === appId ? { ...a, status, updated_at: new Date().toISOString() } : a)),
      );
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setSavingId(null);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  const tiles = [
    { label: "Pipeline", value: stats?.total_applied ?? 0, icon: ListChecks, color: "text-cyan-600" },
    { label: "Shortlisted", value: stats?.shortlisted ?? 0, icon: TrendingUp, color: "text-amber-400" },
    { label: "Interviews", value: stats?.interview ?? 0, icon: Eye, color: "text-indigo-400" },
    { label: "Offers", value: stats?.offer ?? 0, icon: CheckCircle, color: "text-emerald-400" },
    { label: "Hired", value: stats?.hired ?? 0, icon: Award, color: "text-teal-300" },
    { label: "Rejected", value: stats?.rejected ?? 0, icon: XCircle, color: "text-rose-400" },
    { label: "Saved", value: stats?.saved ?? 0, icon: Clock, color: "text-teal-400" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="border-b border-zinc-800/80 pb-6">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
          <ListChecks className="h-4 w-4" />
          Application Tracker
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">Your Pipeline</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Keep track of where every application stands as you move through hiring stages.
        </p>
      </div>

      {/* Stat tiles */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
            <div className="flex items-center justify-between text-zinc-400">
              <span className="text-[11px] font-medium uppercase tracking-wider">{tile.label}</span>
              <tile.icon className={`h-4 w-4 ${tile.color}`} />
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-100">{tile.value}</p>
          </div>
        ))}
      </div>

      {/* Historical observation (§18) */}
      {stats?.observation_note && (
        <div className="mt-4 rounded-xl border border-teal-500/25 bg-teal-500/[0.06] p-4 text-xs leading-relaxed text-zinc-200">
          <span className="font-semibold text-teal-500">Observation:</span>{" "}
          {stats.observation_note}
          {stats.successful_skills && stats.successful_skills.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {stats.successful_skills.map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400 ring-1 ring-emerald-500/25"
                >
                  {s}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-6 flex items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Application rows */}
      <div className="mt-6 space-y-3">
        {apps.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
            <ListChecks className="mx-auto mb-3 h-10 w-10 text-zinc-600" />
            <h3 className="text-lg font-semibold text-zinc-200">No applications yet</h3>
            <p className="mt-1 text-sm text-zinc-400">
              Apply from a job page — or pick up a saved job from your list.
            </p>
            <div className="mt-4 flex justify-center gap-3">
              <Link
                href="/recommendations"
                className="rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
              >
                Browse AI Matches
              </Link>
              <Link
                href="/saved"
                className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs font-semibold text-zinc-300 hover:text-zinc-100"
              >
                Saved Jobs
              </Link>
            </div>
          </div>
        ) : (
          apps.map((app) => (
            <div
              key={app.id}
              className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-4"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/jobs/${app.job_id}`}
                      className="truncate font-semibold text-zinc-100 hover:text-teal-400"
                    >
                      {app.job?.title || "Job posting"}
                    </Link>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold capitalize ring-1 ring-inset whitespace-nowrap ${
                        STATUS_STYLES[app.status] || "bg-zinc-800 text-zinc-300 ring-zinc-700"
                      }`}
                    >
                      {app.status}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">
                    {app.job?.company?.name ? `${app.job.company.name} · ` : ""}
                    Applied {new Date(app.applied_at).toLocaleDateString()}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2 shrink-0">
                  <select
                    value={app.status}
                    disabled={savingId === app.id}
                    onChange={(e) => handleStatusChange(app.id, e.target.value as ApplicationStatus)}
                    className="h-8 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 text-xs text-zinc-200 focus:border-teal-500 focus:outline-none disabled:opacity-50"
                    aria-label={`Status for ${app.job?.title || "application"}`}
                  >
                    {PIPELINE_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </option>
                    ))}
                  </select>
                  <Link
                    href={`/jobs/${app.job_id}`}
                    className="inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs text-zinc-300 hover:border-teal-500/40 hover:text-teal-400"
                  >
                    Open <ExternalLink className="h-3 w-3" />
                  </Link>
                  <button
                    type="button"
                    onClick={() => toggleHistory(app.id)}
                    className="inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs text-zinc-300 hover:border-teal-500/40 hover:text-teal-400"
                    aria-label="View status transition history"
                  >
                    <History className="h-3 w-3 text-teal-400" />
                    History
                    {historyOpen[app.id] ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>
                </div>
              </div>

              {historyOpen[app.id] && (
                <div className="w-full mt-3 border-t border-zinc-800/80 pt-3 text-xs">
                  <div className="font-semibold text-zinc-300 mb-2 flex items-center gap-1.5">
                    <History className="h-3.5 w-3.5 text-teal-400" /> Status Audit Trail
                  </div>
                  {loadingHistory[app.id] ? (
                    <div className="text-zinc-500 animate-pulse">Loading transition log...</div>
                  ) : (historyData[app.id] || []).length === 0 ? (
                    <div className="text-zinc-500">No previous status transitions recorded.</div>
                  ) : (
                    <ol className="relative border-l border-zinc-800 ml-2 space-y-2.5">
                      {historyData[app.id].map((h, i) => (
                        <li key={h.id || i} className="ml-3">
                          <span className="absolute -left-1.5 mt-1 h-3 w-3 rounded-full border border-teal-500 bg-zinc-950" />
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-teal-300 uppercase tracking-wide">
                              {h.new_status}
                            </span>
                            {h.previous_status && (
                              <span className="text-zinc-500 text-[11px]">
                                (from {h.previous_status})
                              </span>
                            )}
                            <span className="text-zinc-500 text-[11px] ml-auto">
                              {new Date(h.changed_at).toLocaleString()}
                            </span>
                          </div>
                          {h.reason && (
                            <p className="text-zinc-400 mt-0.5 text-[11px] italic">
                              Reason: {h.reason}
                            </p>
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {apps.length > 0 && (
        <div className="mt-6 flex justify-end">
          <Link
            href="/saved"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-400 hover:text-teal-300"
          >
            View saved jobs <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}
    </div>
  );
}
