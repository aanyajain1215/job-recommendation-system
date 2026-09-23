"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { discoverCareers } from "@/lib/api";
import { DiscoverResponse, FamilySuggestion } from "@/lib/types";
import {
  AlertCircle,
  ArrowRight,
  GitBranch,
  Loader2,
  Map,
  Route,
  Shuffle,
  Sparkles,
  Target,
} from "lucide-react";

function affinityColor(affinity: number): string {
  if (affinity >= 70) return "bg-emerald-400";
  if (affinity >= 55) return "bg-teal-400";
  if (affinity >= 40) return "bg-cyan-400";
  return "bg-zinc-500";
}

function AffinityCard({
  entry,
  threshold,
}: {
  entry: FamilySuggestion;
  threshold?: number;
}) {
  return (
    <div className="group rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5 transition-colors hover:border-zinc-700">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-white truncate">{entry.family}</h3>
          <span className="text-[11px] text-zinc-500">
            {entry.matched_count}/{entry.core_skill_count} core skills matched
            {entry.transfer_count > 0 && ` · ${entry.transfer_count} transferable`}
          </span>
        </div>
        <div className="text-right flex-shrink-0">
          <span className="text-lg font-black text-zinc-100">{entry.affinity}</span>
          <span className="text-xs font-semibold text-zinc-500">/100</span>
        </div>
      </div>

      {/* Affinity meter */}
      <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden mb-1">
        <div
          className={`h-full rounded-full ${affinityColor(entry.affinity)} transition-all`}
          style={{ width: `${Math.min(100, entry.affinity)}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-zinc-600 mb-3">
        <span>
          overlap {entry.overlap} · semantic {entry.semantic}
        </span>
        {threshold !== undefined && <span>τ = {threshold}</span>}
      </div>

      {/* Evidence explanation (§11 contract) */}
      {entry.explanation.top_skills.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mr-0.5">
            Your edge:
          </span>
          {entry.explanation.top_skills.map((skill) => (
            <span
              key={skill}
              className="rounded-md border border-teal-500/20 bg-teal-500/10 px-2 py-0.5 text-[11px] font-medium text-teal-300"
            >
              {skill}
            </span>
          ))}
        </div>
      )}
      {entry.explanation.nearest_edge && (
        <p className="flex items-center gap-1.5 text-[11px] text-zinc-500">
          <GitBranch className="h-3 w-3 flex-shrink-0 text-violet-400" />
          <span className="truncate">
            {entry.explanation.nearest_edge.from} → {entry.explanation.nearest_edge.to} (
            {entry.explanation.nearest_edge.relation})
          </span>
        </p>
      )}
      <p className="mt-1.5 text-[11px] leading-relaxed text-zinc-500">
        {entry.explanation.note}
      </p>
    </div>
  );
}

export default function CareersPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDiscovery = useCallback(async () => {
    if (!token) return;
    try {
      const res = await discoverCareers(token);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to explore careers");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.push("/login");
      return;
    }
    fetchDiscovery();
  }, [user, authLoading, router, fetchDiscovery]);

  if (authLoading || loading) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-4 border-teal-500/20 border-t-teal-400 animate-spin" />
          <Map className="h-6 w-6 text-teal-400 absolute inset-0 m-auto animate-pulse" />
        </div>
        <p className="mt-4 text-sm text-zinc-400 font-medium">
          Mapping your skills across career families...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-8 max-w-md text-center">
          <AlertCircle className="h-10 w-10 text-rose-400 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-zinc-100">Could not explore careers</h3>
          <p className="mt-2 text-sm text-zinc-400">{error}</p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              fetchDiscovery();
            }}
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-200 hover:bg-zinc-700 transition-colors"
          >
            <Loader2 className="h-4 w-4" /> Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="min-h-screen bg-zinc-950 pb-20 text-zinc-100">
      {/* Hero */}
      <div className="relative overflow-hidden border-b border-zinc-800 bg-gradient-to-b from-teal-950/30 via-zinc-950 to-zinc-950 py-10 px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-6xl">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs font-bold text-teal-300 mb-3">
            <Route className="h-3.5 w-3.5" /> Alternative Career Discovery
          </span>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white">
            Where else your skills take you
          </h1>
          <p className="mt-2 text-sm text-zinc-400 max-w-2xl">
            Families ranked by a deterministic blend of skill overlap and embedding
            similarity. Everything below τ is hidden — nothing is padded.
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 font-semibold text-zinc-300">
              Threshold τ = {data.threshold}
            </span>
            <span className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 font-semibold text-zinc-300">
              {data.explored} families explored
            </span>
            {data.target_family && (
              <span className="rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 font-semibold text-violet-300">
                current: {data.target_family}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 mt-8 space-y-10">
        {/* Thresholded suggestions */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Sparkles className="h-4 w-4 text-teal-400" />
            <h2 className="text-lg font-bold text-white">Above your threshold</h2>
          </div>
          {data.suggestions.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-10 text-center">
              <Target className="h-10 w-10 text-zinc-600 mx-auto mb-3" />
              <h3 className="text-base font-semibold text-zinc-200">
                No family clears τ = {data.threshold} yet
              </h3>
              <p className="mt-2 text-sm text-zinc-500 max-w-md mx-auto">
                Your current skills are concentrated in one direction. Add a few more
                skills or projects to your profile — or start from the curated
                directions below, rendered with the exact same math.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.suggestions.map((entry) => (
                <AffinityCard key={entry.family_id} entry={entry} threshold={data.threshold} />
              ))}
            </div>
          )}
        </section>

        {/* Presets — always shown, same affinity math */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Shuffle className="h-4 w-4 text-violet-400" />
            <h2 className="text-lg font-bold text-white">Curated starting points</h2>
            <span className="text-xs text-zinc-600">· same scoring, never threshold-filtered</span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {data.presets.map((entry) => (
              <AffinityCard key={entry.family_id} entry={entry} />
            ))}
          </div>
        </section>

        {/* Cross-links */}
        <div className="rounded-2xl border border-teal-500/25 bg-gradient-to-r from-teal-950/40 to-zinc-900/60 p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-white">See what a switch would cost</h3>
            <p className="mt-1 text-xs text-zinc-400 max-w-lg">
              The What-If simulator re-scores your profile against every candidate job
              under any mutation — skills, salary, location, or work mode.
            </p>
          </div>
          <Link
            href="/simulator"
            className="inline-flex items-center gap-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-zinc-950 font-semibold px-5 py-2.5 text-sm transition-all shadow-md shadow-teal-500/20"
          >
            Open simulator <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
