"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getPostingInsights } from "@/lib/api";
import { PostingInsights } from "@/lib/types";
import { formatSalary } from "@/lib/format";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { PostingTabs } from "@/components/posting-tabs";
import {
  ArrowLeft,
  BarChart2,
  Briefcase,
  CheckCircle2,
  Globe,
  Lightbulb,
  Lock,
  TrendingUp,
  Users,
  XCircle,
} from "lucide-react";

function scoreColor(score: number) {
  if (score >= 80) return { text: "text-emerald-300", ring: "border-emerald-500/40" };
  if (score >= 55) return { text: "text-amber-300", ring: "border-amber-500/40" };
  return { text: "text-rose-300", ring: "border-rose-500/40" };
}

export default function InsightsPage() {
  const params = useParams();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [insights, setInsights] = useState<PostingInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!jobId || !token) return;
    try {
      setError(null);
      setInsights(await getPostingInsights(jobId, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load insights");
    } finally {
      setLoading(false);
    }
  }, [jobId, token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (authLoading || !ready) return <EmployerLoading />;

  const health = insights?.jd_health;
  const bench = insights?.benchmark;
  const band = scoreColor(health?.score ?? 0);
  const percentileLabel =
    bench?.midpoint_percentile != null
      ? bench.midpoint_percentile >= 50
        ? `Above ${Math.round(100 - bench.midpoint_percentile)}% of peers`
        : `Below ${Math.round(bench.midpoint_percentile)}% of peers`
      : null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <Link
        href={`/hiring/postings/${jobId}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-400 hover:text-zinc-200"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to posting
      </Link>

      <div className="mt-4">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
          <Lightbulb className="h-4 w-4" />
          Insights
        </div>
        <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
          {loading ? "Loading…" : insights?.title ?? "Posting"}
        </h1>
      </div>

      <div className="mt-4">
        <PostingTabs jobId={jobId} active="insights" />
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="mt-6 h-72 animate-pulse rounded-xl bg-zinc-900/50" />
      ) : (
        <>
          {/* ---------- JD health ---------- */}
          {health && (
            <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
                <div className={`rounded-xl border ${band.ring} bg-zinc-950/60 p-5 text-center`}>
                  <div className={`text-5xl font-bold tabular-nums ${band.text}`}>
                    {Math.round(health.score)}
                    <span className="text-2xl">%</span>
                  </div>
                  <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    JD health
                  </div>
                  <div className={`mt-2 text-sm font-medium ${band.text}`}>
                    {health.score >= 80
                      ? "Ready to perform"
                      : health.score >= 55
                        ? "Solid, a few gaps"
                        : "Needs work before promoting"}
                  </div>
                  <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
                    Instant, deterministic feedback — no guessing, no cost.
                  </p>
                </div>

                <ul className="grid gap-2.5 sm:grid-cols-2">
                  {health.checks.map((c) => (
                    <li
                      key={c.label}
                      className="flex items-start gap-2.5 rounded-lg border border-zinc-800/70 bg-zinc-950/40 px-3.5 py-3"
                    >
                      {c.ok ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                      ) : (
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
                      )}
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-zinc-200">{c.label}</div>
                        <div className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                          {c.detail}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* ---------- Benchmark + supply/demand ---------- */}
          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            {/* Market benchmark */}
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <TrendingUp className="h-4 w-4 text-teal-400" />
                Pay benchmark
              </div>

              {!bench ? (
                <div className="mt-4 rounded-lg border border-dashed border-zinc-800 p-4 text-center">
                  <p className="text-xs text-zinc-500">
                    Add a salary range to this posting to see how it compares to live peers.
                  </p>
                </div>
              ) : (
                <>
                  <div className="mt-4 text-xs text-zinc-500">
                    Median of{" "}
                    <span className="font-semibold text-zinc-300">{bench.peer_jobs}</span> live{" "}
                    {bench.family ? `${bench.family} ` : ""}peer
                    {bench.peer_jobs === 1 ? "" : "s"} (USD, FX-normalised)
                  </div>

                  <div className="mt-3 text-lg font-bold text-zinc-100">
                    {formatSalary(bench.median_min_usd, bench.median_max_usd, "USD") ??
                      "Not enough peer salaries"}
                  </div>

                  {bench.midpoint_percentile != null && (
                    <div className="mt-4">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-zinc-500">Your midpoint</span>
                        <span className="font-semibold text-teal-300">
                          P{Math.round(bench.midpoint_percentile)}
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-teal-500 to-cyan-400"
                          style={{ width: `${Math.round(bench.midpoint_percentile)}%` }}
                        />
                      </div>
                      <div className="mt-1.5 text-[11px] text-zinc-500">{percentileLabel}</div>
                    </div>
                  )}

                  {bench.remote_share != null && (
                    <div className="mt-4 flex items-center gap-2 text-xs text-zinc-400">
                      <Globe className="h-3.5 w-3.5 text-zinc-500" />
                      {Math.round(bench.remote_share * 100)}% of peers are remote
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Supply / demand */}
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 lg:col-span-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                  <BarChart2 className="h-4 w-4 text-teal-400" />
                  Skill supply &amp; demand
                </div>
                <span className="inline-flex items-center gap-1 rounded-lg bg-zinc-950/70 px-2.5 py-1.5 text-[10px] font-medium text-zinc-400 ring-1 ring-inset ring-zinc-800">
                  <Lock className="h-3 w-3 text-zinc-500" />
                  Aggregate counts only — who holds a skill is never shown
                </span>
              </div>

              {insights?.required_skill_market.length ? (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[440px] text-left text-sm">
                    <thead>
                      <tr className="text-[11px] uppercase tracking-wider text-zinc-500">
                        <th className="pb-2 font-medium">Your required skill</th>
                        <th className="pb-2 text-right font-medium">Live jobs</th>
                        <th className="pb-2 text-right font-medium">Seekers</th>
                        <th className="pb-2 text-right font-medium">Gap</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60">
                      {insights.required_skill_market.map((row) => (
                        <tr key={row.skill}>
                          <td className="py-2.5 font-medium text-zinc-200">{row.skill}</td>
                          <td className="py-2.5 text-right tabular-nums text-zinc-300">
                            <span className="inline-flex items-center gap-1">
                              <Briefcase className="h-3 w-3 text-zinc-600" />
                              {row.jobs_requiring}
                            </span>
                          </td>
                          <td className="py-2.5 text-right tabular-nums text-zinc-300">
                            <span className="inline-flex items-center gap-1">
                              <Users className="h-3 w-3 text-zinc-600" />
                              {row.seekers_holding}
                            </span>
                          </td>
                          <td className="py-2.5 text-right">
                            <span
                              className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
                                row.gap > 0
                                  ? "bg-rose-500/10 text-rose-300 ring-rose-500/30"
                                  : "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                              }`}
                            >
                              {row.gap > 0 ? `+${row.gap} scarce` : `${row.gap} covered`}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-3 text-[11px] text-zinc-600">
                    Positive gap = more live jobs demand this than seekers hold it. Consider
                    widening the requirement to adjacent skills — the reverse-match Talent tab
                    already surfaces candidates who can transfer in.
                  </p>
                </div>
              ) : (
                <p className="mt-4 text-xs text-zinc-500">
                  No required skills tagged — add skills (and mark required ones) to see market
                  pressure for each.
                </p>
              )}

              {insights?.family_top_demand.length ? (
                <div className="mt-5 border-t border-zinc-800/70 pt-4">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Most demanded among live peers
                  </div>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {insights.family_top_demand.map((row) => (
                      <span
                        key={row.skill}
                        title={`${row.jobs_requiring} live jobs require it · ${row.seekers_holding} seekers hold it`}
                        className="rounded-full bg-zinc-800/70 px-2.5 py-1 text-xs text-zinc-300 ring-1 ring-inset ring-zinc-700/60"
                      >
                        {row.skill}
                        <span className="ml-1.5 text-zinc-500">{row.jobs_requiring}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
