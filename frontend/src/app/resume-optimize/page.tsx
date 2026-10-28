"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getRecommendations, optimizeResume } from "@/lib/api";
import { RecommendationItem, ResumeOptimizeResponse } from "@/lib/types";
import {
  AlertTriangle,
  CheckCircle2,
  FileSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";

const STATUS_ICON = {
  PASS: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
  WARN: <AlertTriangle className="h-4 w-4 text-amber-400" />,
  FAIL: <XCircle className="h-4 w-4 text-rose-400" />,
};

export default function ResumeOptimizePage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [jobs, setJobs] = useState<RecommendationItem[]>([]);
  const [jobId, setJobId] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ResumeOptimizeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (token && user) {
      getRecommendations(token, 15)
        .then((feed) => {
          const items = feed.items || [];
          setJobs(items);
          if (items.length > 0) setJobId(items[0].job.id);
        })
        .catch(() => setJobs([]))
        .finally(() => setLoading(false));
    }
  }, [user, token, authLoading, router]);

  const runOptimize = useCallback(async () => {
    if (!token || !jobId) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await optimizeResume(jobId, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Optimization failed");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }, [token, jobId]);

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
          <FileSearch className="h-4 w-4" />
          Resume Optimizer · plan §13
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
          ATS Report & Grounded Suggestions
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-zinc-400">
          Two layers: deterministic ATS checks against the job&apos;s requirements, then optional
          LLM bullet rewrites — validated so a skill outside your evidence is never suggested.
        </p>
      </div>

      {/* Job picker */}
      <div className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
        <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400">
          Optimize against job
        </label>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <select
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
            className="flex-1 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
          >
            {jobs.length === 0 && <option value="">No recommendations yet</option>}
            {jobs.map((item) => (
              <option key={item.job.id} value={item.job.id}>
                {item.job.title} — {item.job.company?.name} ({item.match_score}%)
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={runOptimize}
            disabled={!jobId || running}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-teal-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
          >
            <Wrench className={`h-4 w-4 ${running ? "animate-pulse" : ""}`} />
            {running ? "Analyzing…" : "Run Optimizer"}
          </button>
        </div>
        {jobs.length === 0 && (
          <p className="mt-3 text-xs text-zinc-500">
            No recommendations yet — add skills to your{" "}
            <Link href="/profile" className="text-teal-400 underline">
              profile
            </Link>{" "}
            first.
          </p>
        )}
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Disclaimer — anti-fabrication contract */}
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-teal-500/20 bg-teal-500/5 p-4">
            <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-teal-400" />
            <div className="text-xs text-teal-300/90">
              <p className="font-semibold text-teal-400">{result.disclaimer}</p>
              <p className="mt-1 text-teal-300/80">
                Analyzing: <span className="text-zinc-100">{result.job_title}</span>
                {result.violations_dropped > 0 && (
                  <span className="ml-2 text-amber-300">
                    · {result.violations_dropped} suggestion(s) dropped by the evidence validator
                  </span>
                )}
              </p>
            </div>
          </div>

          {/* ATS report */}
          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                  <FileSearch className="h-4 w-4 text-teal-400" />
                  ATS checks
                </h2>
                <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs font-bold text-zinc-100">
                  {result.ats.ats_score}/100
                </span>
              </div>
              <ul className="mt-4 space-y-2.5">
                {result.ats.checks.map((check) => (
                  <li
                    key={check.name}
                    className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800/70 bg-zinc-950/50 px-3 py-2.5"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      {STATUS_ICON[check.status]}
                      <span className="truncate text-xs font-medium capitalize text-zinc-200">
                        {check.name.replace(/_/g, " ")}
                      </span>
                    </div>
                    <span className="truncate text-right text-[11px] text-zinc-400">
                      {check.detail}
                    </span>
                  </li>
                ))}
              </ul>

              {/* Missing keywords / weak evidence */}
              <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-400">
                    Missing keywords
                  </p>
                  {result.ats.missing_keywords.length === 0 ? (
                    <p className="mt-2 text-xs text-zinc-500">None — full keyword coverage.</p>
                  ) : (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {result.ats.missing_keywords.map((k) => (
                        <span
                          key={k}
                          className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300 ring-1 ring-amber-500/20"
                        >
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                    Weak evidence (list-only)
                  </p>
                  {result.ats.weak_evidence.length === 0 ? (
                    <p className="mt-2 text-xs text-zinc-500">None — skills appear in bullets.</p>
                  ) : (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {result.ats.weak_evidence.map((k) => (
                        <span
                          key={k}
                          className="rounded-md bg-rose-500/10 px-2 py-0.5 text-[11px] font-medium text-rose-300 ring-1 ring-rose-500/20"
                        >
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Bullet suggestions */}
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <Sparkles className="h-4 w-4 text-teal-400" />
                Rewrites
              </h2>
              {!result.llm_used ? (
                <div className="mt-4 rounded-lg border border-dashed border-zinc-800 p-5 text-center">
                  <p className="text-xs text-zinc-400">
                    The deterministic ATS report above is complete. Connect an LLM API key to
                    enable grounded bullet rewrites (prompt P9).
                  </p>
                  <p className="mt-2 text-[11px] text-zinc-600">
                    No key? No problem — scores never depend on the LLM.
                  </p>
                </div>
              ) : result.suggestions.length === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  All LLM suggestions were dropped by the evidence validator — nothing fabricated
                  reached you.
                </p>
              ) : (
                <ul className="mt-4 space-y-4">
                  {result.suggestions.map((s, i) => (
                    <li key={i} className="rounded-lg border border-zinc-800/70 bg-zinc-950/50 p-3">
                      <p className="text-[11px] text-zinc-500 line-through">{s.bullet}</p>
                      <p className="mt-1.5 text-xs text-zinc-200">{s.rewrite}</p>
                      {s.issues.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {s.issues.map((issue) => (
                            <span
                              key={issue}
                              className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300"
                            >
                              {issue}
                            </span>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
