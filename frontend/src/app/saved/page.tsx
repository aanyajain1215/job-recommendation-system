"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { applyToJob, getMyApplications, removeSavedJob } from "@/lib/api";
import { ApplicationItem, JobDetail } from "@/lib/types";
import { listExternalSavedJobs, removeExternalSavedJob, ExternalSavedJob } from "@/lib/saved-external";
import { BookmarkCheck, Briefcase, ExternalLink, MapPin, Trash2, Wifi } from "lucide-react";

type SavedViewItem =
  | { kind: "app"; app: ApplicationItem }
  | { kind: "external"; ext: ExternalSavedJob };

export default function SavedJobsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [savedApps, setSavedApps] = useState<ApplicationItem[]>([]);
  const [externalSaved, setExternalSaved] = useState<ExternalSavedJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      const list = await getMyApplications(token);
      setSavedApps(list.filter((a) => a.status === "saved"));
      setExternalSaved(listExternalSavedJobs(user?.id));
    } catch (err) {
      // still show external saved jobs even if API fails
      setExternalSaved(listExternalSavedJobs(user?.id));
      setError(err instanceof Error ? err.message : "Failed to load saved jobs");
    } finally {
      setLoading(false);
    }
  }, [token, user?.id]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (token && user) load();
  }, [user, token, authLoading, router, load]);

  const items: SavedViewItem[] = useMemo(() => {
    const ext: SavedViewItem[] = externalSaved.map((e) => ({ kind: "external", ext: e }));
    const apps: SavedViewItem[] = savedApps.map((a) => ({ kind: "app", app: a }));
    // newest first by saved time where available
    const extSorted = [...ext].sort((a, b) => {
      const aa = a.kind === "external" ? a.ext.saved_at : "";
      const bb = b.kind === "external" ? b.ext.saved_at : "";
      return (bb || "").localeCompare(aa || "");
    });
    const appSorted = [...apps].sort((a, b) => {
      const aa = a.kind === "app" ? String(a.app.updated_at || "") : "";
      const bb = b.kind === "app" ? String(b.app.updated_at || "") : "";
      return bb.localeCompare(aa);
    });
    return [...extSorted, ...appSorted];
  }, [externalSaved, savedApps]);

  const handleUnsave = async (item: SavedViewItem) => {
    if (item.kind === "external") {
      removeExternalSavedJob(item.ext.job.id, user?.id);
      setExternalSaved((prev) => prev.filter((s) => s.job.id !== item.ext.job.id));
      return;
    }
    if (!token) return;
    setBusyId(item.app.id);
    try {
      await removeSavedJob(item.app.id, token);
      setSavedApps((prev) => prev.filter((s) => s.id !== item.app.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to remove saved job");
    } finally {
      setBusyId(null);
    }
  };

  const handleApply = async (item: SavedViewItem) => {
    if (item.kind === "external") {
      const url = item.ext.job.external_url;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      return;
    }
    if (!token) return;
    setBusyId(item.app.id);
    try {
      await applyToJob(item.app.job_id, token);
      setSavedApps((prev) => prev.filter((s) => s.id !== item.app.id));
      router.push("/dashboard");
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
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">Saved Jobs</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Bookmark roles now and apply whenever you&apos;re ready.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
            <BookmarkCheck className="mx-auto mb-3 h-10 w-10 text-zinc-600" />
            <h3 className="text-lg font-semibold text-zinc-200">Nothing saved yet</h3>
            <p className="mt-1 text-sm text-zinc-400">
              Save roles from job details to build your shortlist.
            </p>
            <Link
              href="/jobs"
              className="mt-4 inline-block rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
            >
              Browse Jobs
            </Link>
          </div>
        ) : (
          items.map((item) => {
            const isExt = item.kind === "external";
            const job = isExt ? item.ext.job : item.app.job;
            const key = isExt ? item.ext.saved_id : item.app.id;
            const busy = !isExt && busyId === item.app.id;
            const savedDate = isExt ? item.ext.saved_at : item.app.updated_at;
            const externalUrl = job?.external_url;
            const titleHref = !isExt ? `/jobs/${item.app.job_id}` : externalUrl || "#";
            const isExternalListing = isExt || job?.source === "adzuna" || String(job?.id || "").startsWith("adzuna-");

            return (
              <div
                key={key}
                className="flex flex-col gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 transition-colors hover:border-teal-500/30 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Briefcase className="h-4 w-4 flex-shrink-0 text-teal-400" />
                    {isExt ? (
                      <a
                        href={externalUrl || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="truncate font-semibold text-zinc-100 hover:text-teal-400 inline-flex items-center gap-1"
                      >
                        {job?.title || "Job posting"}
                        <ExternalLink className="h-3 w-3 opacity-70" />
                      </a>
                    ) : (
                      <Link
                        href={titleHref}
                        className="truncate font-semibold text-zinc-100 hover:text-teal-400"
                      >
                        {job?.title || "Job posting"}
                      </Link>
                    )}
                    {isExternalListing && (
                      <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-300 ring-1 ring-sky-500/30">
                        Live · Adzuna
                      </span>
                    )}
                    {job?.is_remote && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2 py-0.5 text-[10px] font-medium text-teal-300 ring-1 ring-teal-500/20">
                        <Wifi className="h-2.5 w-2.5" /> Remote
                      </span>
                    )}
                  </div>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-400">
                    {job?.company?.name && <span>{job.company.name}</span>}
                    {job?.location && (
                      <span className="flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {job.location}
                      </span>
                    )}
                    {savedDate && <span>Saved {new Date(savedDate).toLocaleDateString()}</span>}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {externalUrl ? (
                    <button
                      type="button"
                      onClick={() => handleApply(item)}
                      disabled={busy}
                      className="rounded-lg bg-teal-500 px-3.5 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
                    >
                      {busy ? "Working…" : "Apply Now ↗"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleApply(item)}
                      disabled={busy}
                      className="rounded-lg bg-teal-500 px-3.5 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
                    >
                      {busy ? "Working…" : "Apply Now"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleUnsave(item)}
                    disabled={busy}
                    title="Remove from saved"
                    className="rounded-lg border border-zinc-800 p-1.5 text-zinc-500 hover:border-rose-500/40 hover:text-rose-400 disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
