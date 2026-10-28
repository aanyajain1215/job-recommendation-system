"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { applyToJob, getMyApplications, removeSavedJob } from "@/lib/api";
import { ApplicationItem } from "@/lib/types";
import { BookmarkCheck, Briefcase, MapPin, Trash2, Wifi } from "lucide-react";

export default function SavedJobsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [saved, setSaved] = useState<ApplicationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      const list = await getMyApplications(token);
      setSaved(list.filter((a) => a.status === "saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved jobs");
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

  const handleUnsave = async (appId: string) => {
    if (!token) return;
    setBusyId(appId);
    try {
      await removeSavedJob(appId, token);
      setSaved((prev) => prev.filter((s) => s.id !== appId));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to remove saved job");
    } finally {
      setBusyId(null);
    }
  };

  const handleApply = async (app: ApplicationItem) => {
    if (!token) return;
    setBusyId(app.id);
    try {
      await applyToJob(app.job_id, token);
      setSaved((prev) => prev.filter((s) => s.id !== app.id));
      router.push("/tracker");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to apply");
      setBusyId(null);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="border-b border-zinc-800/80 pb-6">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
          <BookmarkCheck className="h-4 w-4" />
          Saved for later
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">Saved Jobs</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Shortlist roles now, apply when you&apos;re ready — saved rows persist as{" "}
          <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] text-teal-300">status=saved</code>.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {saved.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
            <BookmarkCheck className="mx-auto mb-3 h-10 w-10 text-zinc-600" />
            <h3 className="text-lg font-semibold text-zinc-200">Nothing saved yet</h3>
            <p className="mt-1 text-sm text-zinc-400">
              Save roles from a job page to build your shortlist.
            </p>
            <Link
              href="/recommendations"
              className="mt-4 inline-block rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
            >
              Browse AI Matches
            </Link>
          </div>
        ) : (
          saved.map((app) => (
            <div
              key={app.id}
              className="flex flex-col gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 transition-colors hover:border-teal-500/30 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Briefcase className="h-4 w-4 flex-shrink-0 text-teal-400" />
                  <Link
                    href={`/jobs/${app.job_id}`}
                    className="truncate font-semibold text-white hover:text-teal-400"
                  >
                    {app.job?.title || "Job posting"}
                  </Link>
                  {app.job?.is_remote && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2 py-0.5 text-[10px] font-medium text-teal-300 ring-1 ring-teal-500/20">
                      <Wifi className="h-2.5 w-2.5" /> Remote
                    </span>
                  )}
                </div>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-400">
                  {app.job?.company?.name && <span>{app.job.company.name}</span>}
                  {app.job?.location && (
                    <span className="flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {app.job.location}
                    </span>
                  )}
                  <span>Saved {new Date(app.updated_at).toLocaleDateString()}</span>
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {app.job?.external_url ? (
                  // Open the live posting in a new tab; still flip the saved row
                  // to an application internally (Tracker keeps working).
                  <a
                    href={app.job.external_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => handleApply(app)}
                    className="rounded-lg bg-teal-500 px-3.5 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
                  >
                    {busyId === app.id ? "Working…" : "Apply Now ↗"}
                  </a>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleApply(app)}
                    disabled={busyId === app.id}
                    className="rounded-lg bg-teal-500 px-3.5 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
                  >
                    {busyId === app.id ? "Working…" : "Apply Now"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => handleUnsave(app.id)}
                  disabled={busyId === app.id}
                  title="Remove from saved"
                  className="rounded-lg border border-zinc-800 p-1.5 text-zinc-500 hover:border-rose-500/40 hover:text-rose-400 disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
