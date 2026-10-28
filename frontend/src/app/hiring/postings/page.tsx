"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import {
  deleteJob,
  duplicatePosting,
  getEmployerJobs,
  setPostingStatus,
} from "@/lib/api";
import { JobDetail, JobStatus } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { StatusPill } from "@/components/status-pill";
import {
  Copy,
  Eye,
  EyeOff,
  FileText,
  MapPin,
  Pencil,
  PlusCircle,
  Trash2,
  Users,
} from "lucide-react";

type Filter = "all" | JobStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "published", label: "Published" },
  { key: "draft", label: "Drafts" },
  { key: "closed", label: "Closed" },
  { key: "archived", label: "Archived" },
];

export default function PostingsPage() {
  const { token, ready, isLoading } = useEmployerAuth();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [jobs, setJobs] = useState<JobDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      setJobs(await getEmployerJobs(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load postings");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  /** Lifecycle transition, applying the response so the row updates at once. */
  const changeStatus = async (job: JobDetail, next: JobStatus) => {
    if (!token) return;
    setBusyId(job.id);
    try {
      const updated = await setPostingStatus(job.id, next, token);
      setJobs((prev) => prev.map((j) => (j.id === job.id ? { ...j, ...updated } : j)));
      const verbs: Record<JobStatus, string> = {
        published: next === "published" ? "published" : "updated",
        draft: "moved to draft",
        closed: "closed",
        archived: "archived",
      };
      toast.success(`“${job.title}” ${verbs[next]}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update status");
    } finally {
      setBusyId(null);
    }
  };

  const duplicate = async (job: JobDetail) => {
    if (!token) return;
    setBusyId(job.id);
    try {
      await duplicatePosting(job.id, token);
      toast.success("Cloned to a new draft — review it before publishing.");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not duplicate");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (job: JobDetail) => {
    if (!token) return;
    setBusyId(job.id);
    try {
      await deleteJob(job.id, token);
      setJobs((prev) => prev.filter((j) => j.id !== job.id));
      setConfirmDelete(null);
      toast.success("Posting deleted.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    } finally {
      setBusyId(null);
    }
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: jobs.length };
    for (const j of jobs) c[j.status] = (c[j.status] ?? 0) + 1;
    return c;
  }, [jobs]);

  const visible = useMemo(
    () => (filter === "all" ? jobs : jobs.filter((j) => j.status === filter)),
    [jobs, filter],
  );

  if (isLoading || !ready) return <EmployerLoading />;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
            <FileText className="h-4 w-4" />
            Postings
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
            Manage your postings
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Publish, close, clone or delete the roles you&apos;ve posted.
          </p>
        </div>
        <Link
          href="/jobs/new"
          className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all"
        >
          <PlusCircle className="h-4 w-4" />
          Post a job
        </Link>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* Filter tabs */}
      <div className="mt-8 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              filter === f.key
                ? "bg-teal-500/15 text-teal-300 ring-1 ring-inset ring-teal-500/30"
                : "text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200"
            }`}
          >
            {f.label}
            <span className="ml-1.5 text-xs opacity-70">{counts[f.key] ?? 0}</span>
          </button>
        ))}
      </div>

      {/* List */}
      {loading ? (
        <div className="mt-6 h-64 animate-pulse rounded-xl bg-zinc-900/50" />
      ) : visible.length === 0 ? (
        <div className="mt-6 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
          <FileText className="mx-auto h-8 w-8 text-zinc-600" />
          <p className="mt-3 text-sm font-medium text-zinc-300">
            {filter === "all" ? "No postings yet" : `No ${filter} postings`}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {filter === "all"
              ? "Publish your first role to start receiving applicants."
              : "Try another filter."}
          </p>
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {visible.map((job) => {
            const busy = busyId === job.id;
            const isOpen = job.status === "published";
            return (
              <div
                key={job.id}
                className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 transition-colors hover:border-zinc-700/70"
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/hiring/postings/${job.id}`}
                        className="text-sm font-semibold text-zinc-100 hover:text-teal-300"
                      >
                        {job.title}
                      </Link>
                      <StatusPill status={job.status} />
                      {job.family && (
                        <span className="rounded-full bg-zinc-800/70 px-2 py-0.5 text-[10px] font-medium text-zinc-400">
                          {job.family}
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {job.location}
                        {job.is_remote && " · Remote"}
                      </span>
                      {job.salary_min || job.salary_max ? (
                        <span>
                          {formatSalary(job.salary_min, job.salary_max, job.salary_currency)}
                        </span>
                      ) : null}
                      <span className="inline-flex items-center gap-1">
                        <Users className="h-3 w-3" />
                        {job.applicant_count ?? 0} applicant
                        {(job.applicant_count ?? 0) === 1 ? "" : "s"}
                      </span>
                      <span>{new Date(job.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/hiring/postings/${job.id}`}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                    >
                      <Eye className="h-3.5 w-3.5" />
                      View
                    </Link>
                    <Link
                      href={`/hiring/postings/${job.id}/edit`}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Edit
                    </Link>

                    {isOpen ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => changeStatus(job, "closed")}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                      >
                        <EyeOff className="h-3.5 w-3.5" />
                        Close
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => changeStatus(job, "published")}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-600/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        {job.status === "archived" ? "Restore & publish" : "Publish"}
                      </button>
                    )}

                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => duplicate(job)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      Duplicate
                    </button>

                    {confirmDelete === job.id ? (
                      <span className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => remove(job)}
                          className="rounded-lg bg-rose-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
                        >
                          Confirm delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-zinc-800"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => setConfirmDelete(job.id)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-400 hover:border-rose-500/40 hover:text-rose-300 disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {isAdmin && (
        <p className="mt-6 text-xs text-zinc-600">
          Viewing as admin: actions apply to the selected employer&apos;s tenant.
        </p>
      )}
    </div>
  );
}
