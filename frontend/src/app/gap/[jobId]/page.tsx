"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getJobGap } from "@/lib/api";
import { GapResponse } from "@/lib/types";
import { ExplanationCard } from "@/components/explanation-card";
import { GapColumns } from "@/components/gap-columns";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Layers,
  Loader2,
  Target,
  Zap,
} from "lucide-react";

// Skill gap analysis for one job (plan §8 + §12): every number comes from
// the deterministic engine — this page only arranges it.
export default function GapPage() {
  const router = useRouter();
  const params = useParams<{ jobId: string }>();
  const jobId = params?.jobId;
  const { user, token, isLoading: authLoading } = useAuth();
  const [gap, setGap] = useState<GapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user || !token) {
      router.push("/login");
      return;
    }
    if (!jobId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await getJobGap(jobId, token);
        if (!cancelled) setGap(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load the gap analysis");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, token, authLoading, jobId, router]);

  if (authLoading || (loading && !gap)) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-4 border-teal-500/20 border-t-teal-400 animate-spin" />
          <Target className="h-6 w-6 text-teal-400 absolute inset-0 m-auto animate-pulse" />
        </div>
        <p className="mt-4 text-sm text-zinc-400 font-medium">
          Classifying every required skill against your profile...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-8 max-w-md text-center">
          <AlertCircle className="h-10 w-10 text-rose-400 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-zinc-100">Could not load the gap analysis</h3>
          <p className="mt-2 text-sm text-zinc-400">{error}</p>
          <Link
            href="/recommendations"
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-200 hover:bg-zinc-700 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" /> Back to AI Matches
          </Link>
        </div>
      </div>
    );
  }

  if (!gap) return null;

  return (
    <div className="min-h-screen bg-zinc-950 pb-20 text-zinc-100">
      {/* Hero */}
      <div className="relative overflow-hidden border-b border-zinc-800 bg-gradient-to-b from-teal-950/30 via-zinc-950 to-zinc-950 py-10 px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-6xl">
          <Link
            href="/recommendations"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-400 hover:text-teal-300 transition-colors mb-4"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> AI Matches
          </Link>
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs font-bold text-teal-300">
              <Layers className="h-3.5 w-3.5" /> Skill Gap Analysis
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white">
            {gap.job_title}
          </h1>
          <div className="mt-4 flex flex-wrap gap-3 text-xs sm:text-sm">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 font-bold text-emerald-400">
              <Zap className="h-3.5 w-3.5 fill-current" /> {gap.match_score}% Match
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 font-semibold text-zinc-300">
              Skill match {gap.gap_score}%
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 font-semibold text-zinc-300">
              Readiness {Math.round(gap.readiness.value * 100)}% · {gap.readiness.band}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 font-semibold text-amber-300">
              <AlertCircle className="h-3.5 w-3.5" /> {gap.counts.missing} missing
            </span>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 mt-8 space-y-8">
        {/* Deterministic explanation (§12 contract) */}
        <ExplanationCard gap={gap} />

        {/* Quick facts: weakest link + required gaps */}
        {(gap.weakest_link || gap.missing_required.length > 0) && (
          <div className="grid gap-3 sm:grid-cols-2">
            {gap.weakest_link && (
              <div className="rounded-2xl border border-rose-500/25 bg-rose-500/5 p-4">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                  <Target className="h-3.5 w-3.5" /> Weakest link
                </span>
                <p className="mt-1.5 text-lg font-bold text-white">{gap.weakest_link}</p>
                <p className="mt-0.5 text-xs text-zinc-400">
                  Highest weight × still missing — start here.
                </p>
              </div>
            )}
            {gap.missing_required.length > 0 && (
              <div className="rounded-2xl border border-amber-500/25 bg-amber-500/5 p-4">
                <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-400">
                  <AlertCircle className="h-3.5 w-3.5" /> Missing &amp; required
                </span>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {gap.missing_required.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-300"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Four-class columns (§8) */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-bold text-white">Every requirement, classified</h2>
              <p className="text-xs text-zinc-500 mt-0.5">
                Hover any chip for the evidence behind its class.
              </p>
            </div>
            <span className="text-xs text-zinc-500">{gap.classes.length} requirements</span>
          </div>
          <GapColumns gap={gap} />
        </section>

        {/* CTA → roadmap */}
        <div className="rounded-2xl border border-teal-500/25 bg-gradient-to-r from-teal-950/40 to-zinc-900/60 p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-white">Turn this gap into a plan</h3>
            <p className="mt-1 text-xs text-zinc-400 max-w-lg">
              The roadmap sequences the missing skills into phases with hour estimates —
              built from this exact analysis.
            </p>
          </div>
          <Link
            href={`/roadmap?jobId=${gap.job_id}`}
            className="inline-flex items-center gap-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-zinc-950 font-semibold px-5 py-2.5 text-sm transition-all shadow-md shadow-teal-500/20"
          >
            Build my roadmap
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
