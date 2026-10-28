"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getEmployerJobs, getMyCompany } from "@/lib/api";
import { CompanyDetail, JobDetail } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { StatusPill } from "@/components/status-pill";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  FileText,
  MapPin,
  PlusCircle,
  Users,
} from "lucide-react";

function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = "teal",
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: React.ReactNode;
  tone?: "teal" | "amber" | "zinc";
}) {
  const toneCls =
    tone === "teal"
      ? "text-teal-300"
      : tone === "amber"
        ? "text-amber-300"
        : "text-zinc-300";
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          {label}
        </span>
        <span className={toneCls}>{icon}</span>
      </div>
      <div className="mt-3 text-3xl font-bold text-zinc-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

export default function HiringOverviewPage() {
  const { token, ready, isLoading } = useEmployerAuth();
  const { user } = useAuth();
  const [jobs, setJobs] = useState<JobDetail[]>([]);
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    Promise.all([
      getEmployerJobs(token),
      getMyCompany(token).catch(() => null), // employer may have no company yet
    ])
      .then(([jobList, comp]) => {
        if (cancelled) return;
        setJobs(jobList);
        setCompany(comp);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  if (isLoading || !ready) return <EmployerLoading />;

  const published = jobs.filter((j) => j.status === "published");
  const drafts = jobs.filter((j) => j.status === "draft");
  const closed = jobs.filter((j) => j.status === "closed" || j.status === "archived");
  const totalApplicants = jobs.reduce((sum, j) => sum + (j.applicant_count ?? 0), 0);
  const noApplicants = published.filter((j) => (j.applicant_count ?? 0) === 0);

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
            <Building2 className="h-4 w-4" />
            Hiring workspace
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
            {company?.name ?? "Your company"}
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Welcome back{user?.profile?.first_name ? `, ${user.profile.first_name}` : ""} —
            here&apos;s how your postings are doing.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/hiring/postings"
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-2.5 text-sm font-semibold text-zinc-200 hover:bg-zinc-800 transition-colors"
          >
            <FileText className="h-4 w-4" />
            Manage postings
          </Link>
          <Link
            href="/jobs/new"
            className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all"
          >
            <PlusCircle className="h-4 w-4" />
            Post a job
          </Link>
        </div>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* KPI grid */}
      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard
          label="Open postings"
          value={loading ? "…" : published.length}
          hint="Visible to job seekers"
          icon={<FileText className="h-4 w-4" />}
        />
        <KpiCard
          label="Applicants"
          value={loading ? "…" : totalApplicants}
          hint="Across all postings"
          icon={<Users className="h-4 w-4" />}
          tone="zinc"
        />
        <KpiCard
          label="Drafts"
          value={loading ? "…" : drafts.length}
          hint="Not yet published"
          icon={<FileText className="h-4 w-4" />}
          tone="amber"
        />
        <KpiCard
          label="Closed / archived"
          value={loading ? "…" : closed.length}
          hint="No longer receiving applicants"
          icon={<FileText className="h-4 w-4" />}
          tone="zinc"
        />
      </div>

      {/* No company profile yet */}
      {!loading && company === null && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            Your account has no company profile yet — add one so your postings show a company name.
          </div>
          <Link
            href="/hiring/company"
            className="text-sm font-semibold text-amber-300 underline underline-offset-4 hover:text-amber-200"
          >
            Set up company →
          </Link>
        </div>
      )}

      {/* Postings needing attention */}
      {!loading && noApplicants.length > 0 && (
        <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            {noApplicants.length} published posting
            {noApplicants.length > 1 ? "s have" : " has"} no applicants yet
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            These are live but unseen. In later phases you&apos;ll see match-density and market
            feedback here to help them perform.
          </p>
        </div>
      )}

      {/* Recent postings */}
      <div className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-100">Your postings</h2>
          {jobs.length > 0 && (
            <Link
              href="/hiring/postings"
              className="inline-flex items-center gap-1 text-sm font-medium text-teal-400 hover:text-teal-300"
            >
              View all
              <ArrowRight className="h-4 w-4" />
            </Link>
          )}
        </div>

        {loading ? (
          <div className="mt-4 h-40 animate-pulse rounded-xl bg-zinc-900/50" />
        ) : jobs.length === 0 ? (
          <div className="mt-4 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-10 text-center">
            <FileText className="mx-auto h-8 w-8 text-zinc-600" />
            <p className="mt-3 text-sm font-medium text-zinc-300">No postings yet</p>
            <p className="mt-1 text-xs text-zinc-500">
              Publish your first role to start receiving applicants.
            </p>
            <Link
              href="/jobs/new"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
            >
              <PlusCircle className="h-3.5 w-3.5" />
              Post your first job
            </Link>
          </div>
        ) : (
          <div className="mt-4 divide-y divide-zinc-800/60 overflow-hidden rounded-xl border border-zinc-800/80 bg-zinc-900/40">
            {jobs.slice(0, 6).map((job) => (
              <Link
                key={job.id}
                href={`/hiring/postings/${job.id}`}
                className="flex items-center justify-between gap-4 px-4 py-3.5 transition-colors hover:bg-zinc-800/40"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-zinc-100">
                      {job.title}
                    </span>
                    <StatusPill status={job.status} />
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
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
                    <span>
                      Posted {new Date(job.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-4">
                  <div className="text-right">
                    <div className="text-lg font-bold text-zinc-100">
                      {job.applicant_count ?? 0}
                    </div>
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                      applicants
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-zinc-600" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
