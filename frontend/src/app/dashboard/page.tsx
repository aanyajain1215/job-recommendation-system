"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  deleteJob,
  getEmployerJobs,
  getMyApplicationStats,
  getMyProfile,
  getRecommendations,
} from "@/lib/api";
import {
  ApplicationStats,
  JobDetail,
  ProfileDetail,
  RecommendationItem,
} from "@/lib/types";
import {
  ArrowRight,
  Briefcase,
  Building2,
  CheckCircle,
  Clock,
  Compass,
  ExternalLink,
  FileCheck,
  FileText,
  PlusCircle,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingUp,
  User as UserIcon,
  Wifi,
  Zap,
} from "lucide-react";

/** Transient live listing (fetched from Adzuna at query time, no DB row). */
const isLiveJob = (job: JobDetail) =>
  job.source === "adzuna" || job.id.startsWith("adzuna-");

export default function DashboardPage() {
  const router = useRouter();
  const { user, token, isLoading: isAuthLoading } = useAuth();

  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [employerJobs, setEmployerJobs] = useState<JobDetail[]>([]);
  const [topRecommendations, setTopRecommendations] = useState<RecommendationItem[]>([]);
  const [appStats, setAppStats] = useState<ApplicationStats | null>(null);
  const [isDataLoading, setIsDataLoading] = useState(true);

  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.push("/login");
      return;
    }

    if (token && user) {
      if (user.role === "employer" || user.role === "admin") {
        getEmployerJobs(token)
          .then((jobs) => setEmployerJobs(jobs))
          .catch(() => setEmployerJobs([]))
          .finally(() => setIsDataLoading(false));
      } else {
        Promise.all([
          getMyProfile(token).catch(() => null),
          getRecommendations(token, 3).catch(() => null),
          getMyApplicationStats(token).catch(() => null),
        ])
          .then(([prof, recs, stats]) => {
            if (prof) setProfile(prof);
            if (recs) setTopRecommendations(recs.items || []);
            if (stats) setAppStats(stats);
          })
          .finally(() => setIsDataLoading(false));
      }
    }
  }, [user, token, isAuthLoading, router]);

  const handleDeleteJob = async (jobId: string) => {
    if (!token) return;
    if (!confirm("Are you sure you want to delete this job posting?")) return;

    try {
      await deleteJob(jobId, token);
      setEmployerJobs((prev) => prev.filter((j) => j.id !== jobId));
    } catch {
      alert("Failed to delete job posting.");
    }
  };

  if (isAuthLoading || isDataLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-16">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          <p className="text-sm text-zinc-400">Loading your workspace...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Welcome Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-zinc-800/80 pb-8">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-3xl font-bold tracking-tight text-zinc-100">
              Hello,{" "}
              {profile?.first_name || user.profile?.first_name
                ? `${profile?.first_name || user.profile?.first_name}`
                : user.email.split("@")[0]}
            </h1>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                user.role === "employer"
                  ? "bg-indigo-500/10 text-indigo-400 ring-1 ring-indigo-500/30"
                  : user.role === "admin"
                  ? "bg-rose-500/10 text-rose-400 ring-1 ring-rose-500/30"
                  : "bg-teal-500/10 text-teal-300 ring-1 ring-teal-500/30"
              }`}
            >
              {user.role === "employer" ? "Employer" : user.role === "admin" ? "Admin" : "Job Seeker"}
            </span>
          </div>
          <p className="mt-1.5 text-sm text-zinc-400">
            {user.role === "employer"
              ? "Manage your active job postings and candidate pipelines."
              : "Track your profile completeness, tagged skills, and recommendations."}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {user.role === "employer" ? (
            <Link
              href="/jobs/new"
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 hover:bg-indigo-400 transition-colors"
            >
              <PlusCircle className="h-4 w-4" />
              Post a New Job
            </Link>
          ) : (
            <Link
              href="/profile"
              className="inline-flex items-center gap-2 rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-zinc-950 shadow-md shadow-teal-500/20 hover:bg-teal-400 transition-colors"
            >
              <FileText className="h-4 w-4" />
              Edit Profile & Resume
            </Link>
          )}
        </div>
      </div>

      {/* Role-Specific Content */}
      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left 2 Columns */}
        <div className="lg:col-span-2 space-y-6">
          {user.role === "job_seeker" ? (
            <>
              {/* Seeker Profile Overview Card */}
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-teal-500/10 text-teal-400 ring-1 ring-teal-500/30">
                      <UserIcon className="h-6 w-6" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-zinc-100">
                        {profile?.first_name} {profile?.last_name}
                      </h2>
                      <p className="text-xs text-zinc-400">{user.email}</p>
                    </div>
                  </div>
                  <Link
                    href="/profile"
                    className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-300 hover:text-zinc-100"
                  >
                    Edit Profile
                  </Link>
                </div>

                <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-zinc-800/60 pt-5">
                  <div className="rounded-lg bg-zinc-950/50 p-4 border border-zinc-800/50">
                    <p className="text-xs font-medium text-zinc-400">Headline</p>
                    <p className="mt-1 text-sm font-semibold text-zinc-200 line-clamp-1">
                      {profile?.headline || "Add a headline"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-zinc-950/50 p-4 border border-zinc-800/50">
                    <p className="text-xs font-medium text-zinc-400">Location</p>
                    <p className="mt-1 text-sm font-semibold text-zinc-200">
                      {profile?.location || "Not set"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-zinc-950/50 p-4 border border-zinc-800/50">
                    <p className="text-xs font-medium text-zinc-400">Experience</p>
                    <p className="mt-1 text-sm font-semibold text-zinc-200">
                      {profile?.years_of_experience
                        ? `${profile.years_of_experience} yrs`
                        : "Pending"}
                    </p>
                  </div>
                </div>

                {/* Skills Preview */}
                <div className="mt-5 border-t border-zinc-800/60 pt-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                      Skills Tagged ({profile?.skills?.length || 0})
                    </span>
                    <Link href="/profile" className="text-xs text-teal-400 hover:underline">
                      Manage skills
                    </Link>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {profile?.skills && profile.skills.length > 0 ? (
                      profile.skills.map((s, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1 rounded bg-zinc-800/80 px-2 py-0.5 text-xs text-zinc-300"
                        >
                          <Sparkles className="h-2.5 w-2.5 text-teal-400" />
                          {s.skill_name}
                        </span>
                      ))
                    ) : (
                      <p className="text-xs text-zinc-500">No skills tagged yet.</p>
                    )}
                  </div>
                </div>

                {/* Resume Status Box */}
                <div className="mt-5 flex items-center justify-between rounded-lg border border-teal-500/20 bg-teal-500/5 p-4">
                  <div className="flex items-center gap-3">
                    <FileCheck className="h-5 w-5 text-teal-400" />
                    <div>
                      <p className="text-sm font-medium text-zinc-100">
                        {profile?.resume_url ? "Resume Active on File" : "No Resume Uploaded"}
                      </p>
                      <p className="text-xs text-zinc-400">
                        {profile?.resume_url
                          ? "Your resume is stored and ready for ML parsing in Phase 2."
                          : "Upload your resume in PDF/DOCX format to power AI matching."}
                      </p>
                    </div>
                  </div>
                  <Link
                    href="/profile"
                    className="rounded-md bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-700 transition-colors"
                  >
                    {profile?.resume_url ? "Replace File" : "Upload File"}
                  </Link>
                </div>
              </div>

              {/* Seeker Application Pipeline Counters */}
              <div className="grid grid-cols-3 gap-4">
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center justify-between text-zinc-400">
                    <span className="text-xs font-medium uppercase tracking-wider">Applied</span>
                    <Clock className="h-4 w-4 text-cyan-400" />
                  </div>
                  <p className="mt-3 text-2xl font-bold text-zinc-100">
                    {appStats?.total_applied ?? 0}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">Active applications</p>
                </div>
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center justify-between text-zinc-400">
                    <span className="text-xs font-medium uppercase tracking-wider">Shortlisted</span>
                    <TrendingUp className="h-4 w-4 text-teal-400" />
                  </div>
                  <p className="mt-3 text-2xl font-bold text-zinc-100">
                    {appStats?.shortlisted ?? 0}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">Under review</p>
                </div>
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center justify-between text-zinc-400">
                    <span className="text-xs font-medium uppercase tracking-wider">Offers</span>
                    <CheckCircle className="h-4 w-4 text-emerald-400" />
                  </div>
                  <p className="mt-3 text-2xl font-bold text-zinc-100">
                    {appStats?.offer ?? 0}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">Received offers</p>
                </div>
              </div>

              {/* Top AI Matches Widget */}
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
                      <Sparkles className="h-5 w-5 text-teal-400" />
                      Top Recommended Jobs
                    </h2>
                    <p className="text-xs text-zinc-400 mt-0.5">
                      Personalized recommendations based on your skills & profile
                    </p>
                  </div>
                  <Link
                    href="/recommendations"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-300 ring-1 ring-teal-500/30 hover:bg-teal-500/20 transition-colors"
                  >
                    View All Matches
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>

                {topRecommendations.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-zinc-800 p-6 text-center text-xs text-zinc-500">
                    No recommendations found yet. Add more skills to your profile to get matched.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {topRecommendations.map((item) => (
                      <div
                        key={item.job.id}
                        className="flex flex-col justify-between rounded-xl border border-zinc-800/90 bg-zinc-950/50 p-4 hover:border-teal-500/40 transition-all group"
                      >
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ${
                                item.match_score >= 70
                                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                                  : "bg-cyan-500/10 text-cyan-400 border border-cyan-500/30"
                              }`}
                            >
                              <Zap className="h-3 w-3 fill-current" />
                              {item.match_score}% Match
                            </span>
                            {item.job.is_remote && (
                              <span className="text-[10px] text-zinc-400">Remote</span>
                            )}
                          </div>
                          {isLiveJob(item.job) ? (
                            <a
                              href={item.job.external_url || "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="Opens the live posting on Adzuna in a new tab"
                              className="font-semibold text-sm text-zinc-100 group-hover:text-teal-400 line-clamp-1"
                            >
                              {item.job.title}
                            </a>
                          ) : (
                            <Link
                              href={`/jobs/${item.job.id}`}
                              className="font-semibold text-sm text-zinc-100 group-hover:text-teal-400 line-clamp-1"
                            >
                              {item.job.title}
                            </Link>
                          )}
                          <p className="text-xs text-zinc-400 mt-0.5">{item.job.company.name}</p>

                          {item.matched_skills.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1">
                              {item.matched_skills.slice(0, 2).map((s) => (
                                <span
                                  key={s}
                                  className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300 font-medium"
                                >
                                  {s}
                                </span>
                              ))}
                              {item.matched_skills.length > 2 && (
                                <span className="text-[10px] text-zinc-500 self-center">
                                  +{item.matched_skills.length - 2} more
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        {isLiveJob(item.job) ? (
                          <a
                            href={item.job.external_url || "#"}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Opens the live posting on Adzuna in a new tab"
                            className="mt-4 inline-flex items-center justify-between text-xs font-medium text-teal-400 group-hover:text-teal-300 pt-2 border-t border-zinc-800/60"
                          >
                            <span>View on Adzuna</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <Link
                            href={`/jobs/${item.job.id}`}
                            className="mt-4 inline-flex items-center justify-between text-xs font-medium text-teal-400 group-hover:text-teal-300 pt-2 border-t border-zinc-800/60"
                          >
                            <span>Review & Apply</span>
                            <ArrowRight className="h-3 w-3" />
                          </Link>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              {/* Employer Posted Jobs Section */}
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
                      <Briefcase className="h-5 w-5 text-indigo-400" />
                      Your Job Postings ({employerJobs.length})
                    </h2>
                    <p className="text-xs text-zinc-400 mt-0.5">
                      Positions published under {user.companies[0]?.name || "your organization"}
                    </p>
                  </div>
                  <Link
                    href="/jobs/new"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500/20 px-3 py-1.5 text-xs font-semibold text-indigo-300 ring-1 ring-indigo-500/30 hover:bg-indigo-500/30 transition-colors"
                  >
                    <PlusCircle className="h-3.5 w-3.5" />
                    New Posting
                  </Link>
                </div>

                {employerJobs.length === 0 ? (
                  <div className="mt-8 rounded-xl border border-dashed border-zinc-800 p-8 text-center">
                    <Building2 className="mx-auto h-8 w-8 text-zinc-600" />
                    <p className="mt-2 text-sm font-medium text-zinc-100">No active job listings yet</p>
                    <p className="mt-1 text-xs text-zinc-400">
                      Publish your first role to start receiving AI-ranked applicants.
                    </p>
                    <Link
                      href="/jobs/new"
                      className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                    >
                      <PlusCircle className="h-3.5 w-3.5" />
                      Create First Job
                    </Link>
                  </div>
                ) : (
                  <div className="mt-6 space-y-3">
                    {employerJobs.map((job) => (
                      <div
                        key={job.id}
                        className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 hover:border-zinc-700 transition-colors"
                      >
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-zinc-100 hover:text-indigo-300">
                              <Link href={`/jobs/${job.id}`}>{job.title}</Link>
                            </span>
                            {job.is_remote && (
                              <span className="inline-flex items-center gap-1 rounded bg-teal-500/10 px-2 py-0.5 text-[10px] text-teal-300">
                                <Wifi className="h-2.5 w-2.5" />
                                Remote
                              </span>
                            )}
                            <span className="rounded bg-zinc-800 px-2 py-0.5 text-[10px] uppercase text-zinc-300">
                              {job.status}
                            </span>
                          </div>

                          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-zinc-400">
                            <span>{job.location}</span>
                            <span>•</span>
                            <span className="capitalize">{job.employment_type.replace("_", "-")}</span>
                            <span>•</span>
                            <span>{job.skills.length} skills</span>
                            <span>•</span>
                            <span>Posted {new Date(job.created_at).toLocaleDateString()}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3 shrink-0">
                          <Link
                            href={`/jobs/${job.id}`}
                            className="rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-300 hover:text-zinc-100"
                          >
                            View
                          </Link>
                          <button
                            type="button"
                            onClick={() => handleDeleteJob(job.id)}
                            className="rounded p-1.5 text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                            title="Delete posting"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Right Column: Platform Telemetry & Quick Links */}
        <div className="space-y-6">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <ShieldCheck className="h-4 w-4 text-teal-400" />
              Environment & Storage
            </h3>

            <div className="mt-4 space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-zinc-800/60">
                <span className="text-zinc-400">Role</span>
                <span className="font-mono text-zinc-200">{user.role}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-zinc-800/60">
                <span className="text-zinc-400">Storage Volume</span>
                <span className="font-mono text-zinc-200">/app/uploads/resumes</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-zinc-800/60">
                <span className="text-zinc-400">Vector Embeddings</span>
                <span className="font-mono text-teal-400">pgvector ready</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-zinc-400">User ID</span>
                <span className="font-mono text-zinc-500 truncate max-w-[120px]">
                  {user.id}
                </span>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <Compass className="h-4 w-4 text-teal-400" />
              Quick Navigation
            </h3>
            <div className="mt-3 space-y-2">
              <Link
                href="/jobs"
                className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
              >
                Browse All Jobs
              </Link>
              {user.role === "job_seeker" ? (
                <>
                  <Link
                    href="/profile"
                    className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                  >
                    Manage Profile & Skills
                  </Link>
                  <Link
                    href="/tracker"
                    className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                  >
                    Application Tracker
                  </Link>
                  <Link
                    href="/saved"
                    className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                  >
                    Saved Jobs
                  </Link>
                  <Link
                    href="/resume-optimize"
                    className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                  >
                    Resume Optimizer
                  </Link>
                  <Link
                    href="/settings"
                    className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                  >
                    Personalization Settings
                  </Link>
                </>
              ) : (
                <Link
                  href="/jobs/new"
                  className="block rounded-lg border border-zinc-800/80 bg-zinc-950/40 p-3 text-xs text-zinc-300 hover:border-zinc-700 hover:text-zinc-100 transition-colors"
                >
                  Post a New Opportunity
                </Link>
              )}
              {user.role === "admin" && (
                <Link
                  href="/admin"
                  className="block rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-300 hover:border-rose-500/50 hover:text-rose-200 transition-colors"
                >
                  Admin Console
                </Link>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
