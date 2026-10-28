"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import { api, getJobDetail, getMyApplications, saveJob } from "@/lib/api";
import { JobDetail } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import {
  ArrowLeft,
  Bookmark,
  Briefcase,
  Building2,
  Calendar,
  CheckCircle,
  DollarSign,
  ExternalLink,
  Globe,
  MapPin,
  Send,
  Sparkles,
  Wifi,
} from "lucide-react";

export default function JobDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, token } = useAuth();

  const jobId = params?.id as string;
  const [job, setJob] = useState<JobDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasApplied, setHasApplied] = useState(false);

  useEffect(() => {
    if (jobId) {
      getJobDetail(jobId)
        .then((data) => setJob(data))
        .catch((err) => setError(err.message))
        .finally(() => setIsLoading(false));
    }
  }, [jobId]);

  // Check if candidate has already applied on load
  useEffect(() => {
    if (user && token && jobId) {
      getMyApplications(token)
        .then((apps) => {
          if (apps.some((a) => a.job_id === jobId)) {
            setHasApplied(true);
          }
        })
        .catch(() => {});
    }
  }, [user, token, jobId]);

  const { mutate: apply, isPending } = useMutation({
    mutationFn: () => api.post(`/jobs/${jobId}/apply`, { job_id: jobId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications", "me"] });
      queryClient.invalidateQueries({ queryKey: ["applications", "stats"] });
      setHasApplied(true);
      toast.success("Application submitted successfully!");
    },
    onError: (err: unknown) => {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setHasApplied(true); // already applied — not a failure state
        toast.info("You have already applied to this job.");
      } else {
        toast.error(err instanceof Error ? err.message : "Could not submit application");
      }
    },
  });

  const handleApply = (e?: React.MouseEvent) => {
    if (!user) {
      e?.preventDefault();
      router.push("/login");
      return;
    }
    // Send the seeker to the REAL posting in a new tab.  We use a plain
    // <a target="_blank"> (href set in JSX) so this runs as a genuine user
    // gesture — window.open() after an awaited fetch gets popup-blocked.
    // In parallel we still record the application internally so the Tracker,
    // stats and feedback loop keep working.
    apply();
  };

  // Save-for-later (wires the previously dead saveJob() helper so the
  // /saved page's "Save roles from a job page" instruction is real).
  const [isSaved, setIsSaved] = useState(false);
  const { mutate: save, isPending: isSaving } = useMutation({
    mutationFn: () => saveJob(jobId, token!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications", "me"] });
      setIsSaved(true);
      toast.success("Saved — find it under Saved Jobs.");
    },
    onError: (err: unknown) => {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setIsSaved(true);
        toast.info("This job is already in your saved list.");
      } else {
        toast.error(err instanceof Error ? err.message : "Could not save this job");
      }
    },
  });

  const handleSave = () => {
    if (!user) {
      router.push("/login");
      return;
    }
    save();
  };

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-16">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-16 text-center">
        <Briefcase className="mx-auto h-12 w-12 text-zinc-600" />
        <h1 className="mt-4 text-2xl font-bold text-white">Job Not Found</h1>
        <p className="mt-2 text-sm text-zinc-400">The position you are looking for does not exist or has been closed.</p>
        <Link
          href="/jobs"
          className="mt-6 inline-flex items-center gap-2 rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-teal-400"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to all jobs
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Top Back Link */}
      <div className="mb-6">
        <Link
          href="/jobs"
          className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to all opportunities
        </Link>
      </div>

      {/* Main Header Box */}
      <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-8 backdrop-blur">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 text-sm font-semibold text-zinc-300">
                <Building2 className="h-4 w-4 text-indigo-400" />
                {job.company.name}
              </span>
              {job.is_remote && (
                <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-xs font-medium text-teal-300 ring-1 ring-teal-500/30">
                  <Wifi className="h-3 w-3" />
                  Remote
                </span>
              )}
              <span className="rounded bg-zinc-800 px-2.5 py-0.5 text-xs font-medium text-zinc-300 capitalize">
                {job.experience_level} Level
              </span>
              <span className="rounded bg-zinc-800 px-2.5 py-0.5 text-xs font-medium text-zinc-300 capitalize">
                {job.employment_type.replace("_", "-")}
              </span>
            </div>

            <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
              {job.title}
            </h1>

            <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-zinc-400">
              <div className="flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                <span>{job.location}</span>
              </div>
              <div className="flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                <span>Posted {new Date(job.created_at).toLocaleDateString()}</span>
              </div>
              {job.company.website && (
                <div className="flex items-center gap-1">
                  <Globe className="h-3.5 w-3.5 text-zinc-500" />
                  <a
                    href={job.company.website}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:text-teal-400"
                  >
                    {job.company.website}
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* Action Box */}
          <div className="lg:text-right shrink-0">
            {job.salary_min || job.salary_max ? (
              <div className="text-xl font-bold text-white flex items-center lg:justify-end gap-1">
                <DollarSign className="h-5 w-5 text-emerald-400" />
                <span>
                  {formatSalary(job.salary_min, job.salary_max, job.salary_currency)}
                </span>
                <span className="text-xs text-zinc-400 font-normal">/ year</span>
              </div>
            ) : (
              <span className="text-sm font-medium text-zinc-400">Competitive salary</span>
            )}

            <div className="mt-4">
              {hasApplied ? (
                <div className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-5 py-2.5 text-sm font-semibold text-emerald-300">
                  <CheckCircle className="h-4 w-4" />
                  Application Submitted
                </div>
              ) : (
                <div className="flex flex-wrap items-center justify-end gap-3">
                  {job.external_url ? (
                    // Real opening available → open it in a new tab, and still
                    // record the application internally (Tracker/stats) via the
                    // same click handler.
                    <a
                      href={job.external_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={handleApply}
                      className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all"
                    >
                      <Send className="h-4 w-4" />
                      Apply on Company Site
                      <ExternalLink className="h-3.5 w-3.5 opacity-70" />
                    </a>
                  ) : (
                    // Native in-app posting (no external URL) → apply internally.
                    <button
                      type="button"
                      onClick={handleApply}
                      disabled={isPending}
                      className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all disabled:opacity-60 disabled:pointer-events-none"
                    >
                      {isPending ? (
                        <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-950 border-t-transparent" />
                      ) : (
                        <Send className="h-4 w-4" />
                      )}
                      {isPending ? "Submitting Application..." : "Apply with Profile & Resume"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isSaving}
                    className="inline-flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-5 py-3 text-sm font-semibold text-zinc-200 hover:bg-zinc-800 active:scale-[0.98] transition-all disabled:opacity-60"
                  >
                    <Bookmark className="h-4 w-4" />
                    {isSaving ? "Saving..." : isSaved ? "Saved ✓" : "Save Job"}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Grid: Job Content + Required Skills */}
      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* Left 2 Cols: Description & Requirements */}
        <div className="lg:col-span-2 space-y-8">
          <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-4">
            <h2 className="text-lg font-bold text-white">About the Position</h2>
            <div className="text-sm leading-relaxed text-zinc-300 whitespace-pre-wrap">
              {job.description}
            </div>
          </section>

          {job.requirements && (
            <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-4">
              <h2 className="text-lg font-bold text-white">Role Requirements & Qualifications</h2>
              <div className="text-sm leading-relaxed text-zinc-300 whitespace-pre-wrap">
                {job.requirements}
              </div>
            </section>
          )}
        </div>

        {/* Right Col: Required Skills & Model Weights */}
        <div className="space-y-6">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-teal-400" />
              Skill Requirements
            </h3>
            <p className="mt-1 text-xs text-zinc-500">
              Evaluated for ANN candidate matching and ranking scores.
            </p>

            <div className="mt-4 space-y-2.5">
              {job.skills && job.skills.length > 0 ? (
                job.skills.map((sk, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/60 p-2.5 text-xs"
                  >
                    <span className="font-semibold text-zinc-200">{sk.skill_name}</span>
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          sk.is_required
                            ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            : "bg-zinc-800 text-zinc-400"
                        }`}
                      >
                        {sk.is_required ? "Must-have" : "Nice-to-have"}
                      </span>
                      <span className="font-mono text-zinc-400">{sk.importance_weight}x</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-zinc-500">No specific skills tagged.</p>
              )}
            </div>
          </div>

          {/* Company Sidebar */}
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-2">
              <Building2 className="h-4 w-4 text-indigo-400" />
              About {job.company.name}
            </h3>
            <div className="mt-3 space-y-2 text-xs text-zinc-400">
              <p>Organization Slug: <span className="font-mono text-zinc-300">{job.company.slug}</span></p>
              <p>Location: <span className="text-zinc-300">{job.location}</span></p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
