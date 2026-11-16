"use client";

import React, { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import { api, saveJob } from "@/lib/api";
import { JobDetail } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import { isExternalJobSaved, saveExternalJob } from "@/lib/saved-external";
import {
  Bookmark,
  Briefcase,
  Building2,
  Calendar,
  CheckCircle,
  ExternalLink,
  Globe,
  MapPin,
  Send,
  Sparkles,
  Wifi,
  X,
} from "lucide-react";

type Props = {
  job: JobDetail | null;
  open: boolean;
  onClose: () => void;
};

const isLiveJob = (job: JobDetail) =>
  job.source === "adzuna" || String(job.id).startsWith("adzuna-");

export default function JobDetailModal({ job, open, onClose }: Props) {
  const { user, token } = useAuth();
  const queryClient = useQueryClient();
  const [isSaved, setIsSaved] = React.useState(false);

  useEffect(() => {
    if (!open || !job) {
      setIsSaved(false);
      return;
    }
    const live = isLiveJob(job);
    if (live) {
      setIsSaved(isExternalJobSaved(job.id, user?.id));
    } else {
      setIsSaved(false);
    }
  }, [open, job?.id, user?.id]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const { mutate: apply, isPending } = useMutation({
    mutationFn: () => api.post(`/jobs/${job?.id}/apply`, { job_id: job?.id }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["applications", "me"] });
      queryClient.invalidateQueries({ queryKey: ["applications", "stats"] });
      toast.success("Application recorded.");
    },
    onError: (err: unknown) => {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        toast.info("You have already applied to this job.");
      } else {
        toast.error(err instanceof Error ? err.message : "Could not record application");
      }
    },
  });

  const { mutate: save, isPending: isSaving } = useMutation({
    mutationFn: () => saveJob(job!.id, token!),
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

  if (!open || !job) return null;

  const live = isLiveJob(job);

  const handleApply = () => {
    if (!user) {
      toast.info("Please sign in to continue.");
      return;
    }
    // For external/live postings, open the real posting; record internally only for native DB jobs.
    if (!live && !job.external_url) {
      apply();
    } else if (!live && job.external_url) {
      // native job with external url: best-effort record
      apply();
    }
  };

  const handleSave = () => {
    if (!user) {
      toast.info("Please sign in to save jobs.");
      return;
    }
    if (live) {
      if (isExternalJobSaved(job.id, user.id)) {
        setIsSaved(true);
        toast.info("This job is already in your Saved list.");
        return;
      }
      saveExternalJob(job, user.id);
      setIsSaved(true);
      toast.success("Saved — find it under Saved Jobs.");
      return;
    }
    save();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl shadow-black/60">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-zinc-800/80 p-5 sm:p-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5 text-sm font-semibold text-zinc-300">
                <Building2 className="h-4 w-4 text-indigo-400" />
                {job.company?.name || "Company"}
              </span>
              {live && (
                <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-2.5 py-0.5 text-xs font-medium text-sky-300 ring-1 ring-sky-500/30">
                  <ExternalLink className="h-3 w-3" /> Live · Adzuna
                </span>
              )}
              {job.is_remote && (
                <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-xs font-medium text-teal-300 ring-1 ring-teal-500/30">
                  <Wifi className="h-3 w-3" /> Remote
                </span>
              )}
              <span className="rounded bg-zinc-800 px-2.5 py-0.5 text-xs font-medium text-zinc-300 capitalize">
                {job.experience_level} Level
              </span>
              <span className="rounded bg-zinc-800 px-2.5 py-0.5 text-xs font-medium text-zinc-300 capitalize">
                {String(job.employment_type || "").replace("_", "-")}
              </span>
            </div>
            <h2 className="mt-2 text-2xl font-extrabold tracking-tight text-zinc-100 sm:text-3xl">
              {job.title}
            </h2>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-zinc-400">
              <div className="flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                <span>{job.location}</span>
              </div>
              {job.created_at && (
                <div className="flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5 text-zinc-500" />
                  <span>Posted {new Date(job.created_at).toLocaleDateString()}</span>
                </div>
              )}
              {job.company?.website && (
                <div className="flex items-center gap-1">
                  <Globe className="h-3.5 w-3.5 text-zinc-500" />
                  <a href={job.company.website} target="_blank" rel="noreferrer" className="hover:text-teal-400">
                    {job.company.website}
                  </a>
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border border-zinc-800 p-2 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto p-5 sm:p-6">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-6 lg:flex-1">
              <section>
                <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">About the Position</h3>
                <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
                  {job.description || "No description provided."}
                </div>
              </section>
              {job.requirements && (
                <section>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">Requirements</h3>
                  <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
                    {job.requirements}
                  </div>
                </section>
              )}
            </div>

            <div className="w-full space-y-4 lg:w-80 lg:shrink-0">
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
                {job.salary_min || job.salary_max ? (
                  <div className="text-lg font-bold text-zinc-100">
                    {formatSalary(job.salary_min, job.salary_max, job.salary_currency, job.location)}
                    <span className="ml-1 text-xs font-normal text-zinc-400">/ year</span>
                  </div>
                ) : (
                  <span className="text-sm font-medium text-zinc-400">Competitive salary</span>
                )}

                <div className="mt-4 flex flex-col gap-2">
                  {job.external_url ? (
                    <a
                      href={job.external_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={handleApply}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/20 hover:bg-teal-400"
                    >
                      <Send className="h-4 w-4" />
                      {live ? "Apply on Adzuna" : "Apply on Company Site"}
                      <ExternalLink className="h-3.5 w-3.5 opacity-70" />
                    </a>
                  ) : (
                    <button
                      type="button"
                      onClick={handleApply}
                      disabled={isPending}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-60"
                    >
                      {isPending ? <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-950 border-t-transparent" /> : <Send className="h-4 w-4" />}
                      {isPending ? "Submitting..." : "Apply with Profile & Resume"}
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={isSaving}
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-2.5 text-sm font-semibold text-zinc-200 hover:bg-zinc-800 disabled:opacity-60"
                  >
                    <Bookmark className="h-4 w-4" />
                    {isSaving ? "Saving..." : isSaved ? "Saved ✓" : "Save Job"}
                  </button>
                  {live && (
                    <p className="text-[11px] leading-snug text-zinc-500">
                      Live external listing — saved to your Saved Jobs list in this browser.
                    </p>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
                <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                  <Sparkles className="h-4 w-4 text-teal-400" /> Skill Requirements
                </h3>
                <div className="mt-3 space-y-2">
                  {job.skills && job.skills.length > 0 ? (
                    job.skills.map((sk, idx) => (
                      <div key={idx} className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/60 p-2 text-xs">
                        <span className="font-semibold text-zinc-200">{sk.skill_name}</span>
                        <div className="flex items-center gap-2">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${sk.is_required ? "bg-rose-500/10 text-rose-400 border border-rose-500/20" : "bg-zinc-800 text-zinc-400"}`}>
                            {sk.is_required ? "Must-have" : "Nice-to-have"}
                          </span>
                          {typeof sk.importance_weight === "number" && (
                            <span className="font-mono text-zinc-400">{sk.importance_weight}x</span>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-zinc-500">No specific skills tagged.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
