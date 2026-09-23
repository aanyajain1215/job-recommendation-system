"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { completeRoadmapStep, getJobRoadmap } from "@/lib/api";
import { RoadmapResponse, RoadmapStep } from "@/lib/types";
import { PhaseTimeline } from "@/components/phase-timeline";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  Compass,
  Loader2,
  Map,
  Route,
  Sparkles,
} from "lucide-react";

function bandChipClass(band: string): string {
  switch (band) {
    case "high":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "medium":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";
    default:
      return "border-zinc-600 bg-zinc-800 text-zinc-400";
  }
}

function RoadmapContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = searchParams.get("jobId");
  const { user, token, isLoading: authLoading } = useAuth();
  const [roadmap, setRoadmap] = useState<RoadmapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [doneSeqs, setDoneSeqs] = useState<Set<number>>(new Set());
  const [completingSeq, setCompletingSeq] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user || !token) {
      router.push("/login");
      return;
    }
    if (!jobId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await getJobRoadmap(jobId, token);
        if (cancelled) return;
        setRoadmap(data);
        setDoneSeqs(new Set(data.steps.filter((s) => s.done).map((s) => s.seq)));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to build the roadmap");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, token, authLoading, jobId, router]);

  const handleComplete = useCallback(
    async (step: RoadmapStep) => {
      if (!token || !roadmap?.id || !step.id || doneSeqs.has(step.seq)) return;
      setCompletingSeq(step.seq);
      try {
        const res = await completeRoadmapStep(roadmap.id, step.id, token);
        setDoneSeqs((prev) => new Set(prev).add(res.seq));
        setNotice(`Step #${res.seq} complete — ${res.steps_done}/${res.steps_total} done`);
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Could not save that step");
      } finally {
        setCompletingSeq(null);
      }
    },
    [token, roadmap?.id, doneSeqs],
  );

  // No ?jobId= → guide the user back to the feed.
  if (!jobId && !loading) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-10 max-w-md text-center">
          <Compass className="h-10 w-10 text-teal-400 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-zinc-100">No job selected</h3>
          <p className="mt-2 text-sm text-zinc-400">
            Open a roadmap from any recommendation — each one is derived from that
            job&apos;s exact skill gap.
          </p>
          <Link
            href="/recommendations"
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-teal-500 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-teal-400 transition-colors"
          >
            Browse AI Matches <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    );
  }

  if (authLoading || (loading && !roadmap)) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-4 border-teal-500/20 border-t-teal-400 animate-spin" />
          <Route className="h-6 w-6 text-teal-400 absolute inset-0 m-auto animate-pulse" />
        </div>
        <p className="mt-4 text-sm text-zinc-400 font-medium">
          Sequencing skills into phases...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-8 max-w-md text-center">
          <AlertCircle className="h-10 w-10 text-rose-400 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-zinc-100">Could not build the roadmap</h3>
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

  if (!roadmap) return null;

  const doneCount = doneSeqs.size;
  const totalCount = roadmap.steps.length;

  return (
    <div className="min-h-screen bg-zinc-950 pb-20 text-zinc-100">
      {/* Hero */}
      <div className="relative overflow-hidden border-b border-zinc-800 bg-gradient-to-b from-teal-950/30 via-zinc-950 to-zinc-950 py-10 px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl">
          <Link
            href={`/gap/${roadmap.job_id}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-400 hover:text-teal-300 transition-colors mb-4"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Skill gap analysis
          </Link>
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs font-bold text-teal-300">
              <Map className="h-3.5 w-3.5" /> Career Roadmap
            </span>
            {roadmap.effort_band && (
              <span className="inline-flex items-center rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-zinc-300">
                {roadmap.effort_band} effort
              </span>
            )}
          </div>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white">
            {roadmap.job_title}
          </h1>
          <p className="mt-2 text-sm text-zinc-400 max-w-2xl">{roadmap.summary}</p>

          {/* Stats */}
          <div className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-3xl">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <Clock className="h-3 w-3" /> Total effort
              </span>
              <p className="mt-1 text-lg font-black text-white">{roadmap.total_hours}h</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <Sparkles className="h-3 w-3" /> Readiness now
              </span>
              <p className="mt-1 text-lg font-black text-zinc-300">
                {Math.round(roadmap.readiness_before.value * 100)}%
                <span className={`ml-1.5 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase align-middle ${bandChipClass(roadmap.readiness_before.band)}`}>
                  {roadmap.readiness_before.band}
                </span>
              </p>
            </div>
            <div className="rounded-xl border border-teal-500/25 bg-teal-500/5 p-3">
              <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-teal-400">
                <Route className="h-3 w-3" /> After roadmap
              </span>
              <p className="mt-1 text-lg font-black text-teal-300">
                {Math.round(roadmap.readiness_after.value * 100)}%
                <span className={`ml-1.5 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase align-middle ${bandChipClass(roadmap.readiness_after.band)}`}>
                  {roadmap.readiness_after.band}
                </span>
              </p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                <CheckCircle2 className="h-3 w-3" /> Progress
              </span>
              <p className="mt-1 text-lg font-black text-zinc-300">
                {doneCount}
                <span className="text-sm font-semibold text-zinc-500">/{totalCount}</span>
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 mt-8">
        {/* Completion notice */}
        {notice && (
          <div className="mb-5 flex items-center justify-between rounded-xl border border-teal-500/25 bg-teal-500/5 px-4 py-2.5 text-sm text-teal-200">
            <span className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-teal-400" /> {notice}
            </span>
            <button
              onClick={() => setNotice(null)}
              className="text-xs text-teal-400/70 hover:text-teal-300"
            >
              dismiss
            </button>
          </div>
        )}

        {!roadmap.id && (
          <div className="mb-5 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-xs text-amber-300">
            This job has no family anchor yet, so progress tracking is unavailable —
            the plan below is still fully accurate.
          </div>
        )}

        <PhaseTimeline
          roadmap={roadmap}
          doneSeqs={doneSeqs}
          onComplete={roadmap.id ? handleComplete : undefined}
          completingSeq={completingSeq}
        />

        {/* Candidates covered */}
        {roadmap.candidates.length > 0 && (
          <div className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              Skills this roadmap closes
            </span>
            <div className="mt-2.5 flex flex-wrap gap-2">
              {roadmap.candidates.map((skill) => (
                <span
                  key={skill}
                  className="rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-300"
                >
                  {skill}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Cross-links */}
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href={`/gap/${roadmap.job_id}`}
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-700 hover:text-white transition-colors"
          >
            <ArrowLeft className="h-4 w-4" /> Review the gap first
          </Link>
          <Link
            href="/simulator"
            className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-700 hover:text-white transition-colors"
          >
            What-If Simulator <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function RoadmapPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-[70vh] flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-teal-400" />
        </div>
      }
    >
      <RoadmapContent />
    </Suspense>
  );
}
