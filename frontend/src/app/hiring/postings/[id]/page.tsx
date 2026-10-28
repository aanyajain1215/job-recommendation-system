"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import { deleteJob, duplicatePosting, getJobDetail, setPostingStatus } from "@/lib/api";
import { JobDetail, JobStatus } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { StatusPill } from "@/components/status-pill";
import { PostingTabs } from "@/components/posting-tabs";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Calendar,
  CheckCircle2,
  Circle,
  Copy,
  DollarSign,
  Eye,
  EyeOff,
  MapPin,
  Pencil,
  Trash2,
  Users,
} from "lucide-react";

export default function PostingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params?.id as string;
  const { token, ready, isLoading } = useEmployerAuth();
  const { user } = useAuth();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      setError(null);
      setJob(await getJobDetail(jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load posting");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  const changeStatus = async (next: JobStatus) => {
    if (!token || !job) return;
    setBusy(true);
    try {
      const updated = await setPostingStatus(job.id, next, token);
      setJob((prev) => (prev ? { ...prev, ...updated } : prev));
      toast.success(`Posting ${next === "published" ? "published" : next}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update status");
    } finally {
      setBusy(false);
    }
  };

  const duplicate = async () => {
    if (!token || !job) return;
    setBusy(true);
    try {
      const copy = await duplicatePosting(job.id, token);
      toast.success("Cloned to a new draft.");
      router.push(`/hiring/postings/${copy.id}/edit`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not duplicate");
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!token || !job) return;
    setBusy(true);
    try {
      await deleteJob(job.id, token);
      toast.success("Posting deleted.");
      router.push("/hiring/postings");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
      setBusy(false);
    }
  };

  if (isLoading || !ready) return <EmployerLoading />;

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="h-8 w-56 animate-pulse rounded bg-zinc-900" />
        <div className="mt-6 h-64 animate-pulse rounded-xl bg-zinc-900/60" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-6 text-sm text-rose-300">
          {error ?? "Posting not found."}
        </div>
        <Link
          href="/hiring/postings"
          className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-teal-400 hover:text-teal-300"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to postings
        </Link>
      </div>
    );
  }

  const required = (job.skills ?? []).filter((s) => s.is_required);
  const niceToHave = (job.skills ?? []).filter((s) => !s.is_required);
  const isOpen = job.status === "published";

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <Link
        href="/hiring/postings"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-400 hover:text-zinc-200"
      >
        <ArrowLeft className="h-4 w-4" />
        All postings
      </Link>

      {/* Header card */}
      <div className="mt-4 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={job.status} />
              {job.family && (
                <span className="rounded-full bg-zinc-800/70 px-2.5 py-0.5 text-[11px] font-medium text-zinc-400">
                  {job.family}
                </span>
              )}
            </div>
            <h1 className="mt-3 text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
              {job.title}
            </h1>
            <div className="mt-2 flex items-center gap-1.5 text-sm text-zinc-400">
              <Building2 className="h-4 w-4 text-zinc-500" />
              {job.company?.name ?? "No company"}
            </div>
          </div>

          {/* Lifecycle + management actions */}
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/hiring/postings/${job.id}/edit`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-800"
            >
              <Pencil className="h-4 w-4" />
              Edit
            </Link>
            {isOpen ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => changeStatus("closed")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
              >
                <EyeOff className="h-4 w-4" />
                Close posting
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => changeStatus("published")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-600/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
              >
                <Eye className="h-4 w-4" />
                Publish
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={duplicate}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-50"
            >
              <Copy className="h-4 w-4" />
              Duplicate
            </button>
            {confirmDelete ? (
              <span className="inline-flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={busy}
                  onClick={remove}
                  className="rounded-lg bg-rose-500 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
                >
                  Confirm delete
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDelete(false)}
                  className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-800"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmDelete(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm font-medium text-zinc-400 hover:border-rose-500/40 hover:text-rose-300 disabled:opacity-50"
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </button>
            )}
          </div>
        </div>

        {/* Meta strip */}
        <div className="mt-6 grid grid-cols-2 gap-4 border-t border-zinc-800/70 pt-5 sm:grid-cols-4">
          <div>
            <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
              <MapPin className="h-3.5 w-3.5" />
              Location
            </div>
            <div className="mt-1 text-sm font-medium text-zinc-200">
              {job.location}
              {job.is_remote && " · Remote"}
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
              <DollarSign className="h-3.5 w-3.5" />
              Salary
            </div>
            <div className="mt-1 text-sm font-medium text-zinc-200">
              {job.salary_min || job.salary_max
                ? formatSalary(job.salary_min, job.salary_max, job.salary_currency)
                : "Not specified"}
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
              <Calendar className="h-3.5 w-3.5" />
              Posted
            </div>
            <div className="mt-1 text-sm font-medium text-zinc-200">
              {new Date(job.created_at).toLocaleDateString()}
            </div>
          </div>
          <div>
            <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
              <Users className="h-3.5 w-3.5" />
              Applicants
            </div>
            <div className="mt-1 text-sm font-medium text-zinc-200">
              {job.applicant_count ?? 0}
            </div>
          </div>
        </div>
      </div>

      {/* Section tabs (Overview · Applicants · …) */}
      <div className="mt-5">
        <PostingTabs jobId={job.id} active="overview" />
      </div>

      {/* Applicant pipeline CTA */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-5 py-4">
        <div className="flex items-center gap-2 text-sm text-zinc-400">
          <Users className="h-4 w-4 text-teal-400" />
          <span className="font-medium text-zinc-300">Applicant pipeline</span> — you have{" "}
          <span className="font-semibold text-teal-300">{job.applicant_count ?? 0}</span>{" "}
          applicant{(job.applicant_count ?? 0) === 1 ? "" : "s"} on this posting.
        </div>
        <Link
          href={`/hiring/postings/${job.id}/applicants`}
          className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500/10 px-3.5 py-2 text-sm font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30 hover:bg-teal-500/20"
        >
          Open pipeline
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {/* Description + requirements */}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="text-lg font-semibold text-zinc-100">About the role</h2>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
            {job.description}
          </p>

          {job.requirements && (
            <>
              <h2 className="mt-8 text-lg font-semibold text-zinc-100">Requirements</h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
                {job.requirements}
              </p>
            </>
          )}
        </div>

        {/* Skills sidebar */}
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Skills
          </h3>
          <div className="mt-3">
            {required.length > 0 && (
              <>
                <div className="text-xs font-medium text-zinc-500">Required</div>
                <ul className="mt-2 space-y-1.5">
                  {required.map((s) => (
                    <li
                      key={s.skill_name}
                      className="flex items-center gap-2 text-sm text-zinc-200"
                    >
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-teal-400" />
                      {s.skill_name}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {niceToHave.length > 0 && (
              <>
                <div className="mt-5 text-xs font-medium text-zinc-500">Nice to have</div>
                <ul className="mt-2 space-y-1.5">
                  {niceToHave.map((s) => (
                    <li
                      key={s.skill_name}
                      className="flex items-center gap-2 text-sm text-zinc-400"
                    >
                      <Circle className="h-4 w-4 shrink-0 text-zinc-600" />
                      {s.skill_name}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {(job.skills ?? []).length === 0 && (
              <p className="text-sm text-zinc-500">
                No skills tagged. Add skills when editing so matching can work properly.
              </p>
            )}
          </div>

          {user?.role === "admin" && (
            <p className="mt-6 text-xs text-zinc-600">
              Viewing as admin on another employer&apos;s tenant.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
