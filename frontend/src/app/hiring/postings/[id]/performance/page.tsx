"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getPostingPerformance } from "@/lib/api";
import { PostingPerformance } from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { PostingTabs } from "@/components/posting-tabs";
import {
  Activity,
  ArrowLeft,
  BarChart3,
  CalendarClock,
  Flame,
  Gauge,
  Timer,
  TrendingUp,
  Users,
} from "lucide-react";

const HEALTH: Record<
  PostingPerformance["health"],
  { label: string; message: string; chip: string; icon: React.ReactNode }
> = {
  hot: {
    label: "Hot",
    message: "Applications are arriving steadily — keep the pipeline moving.",
    chip: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
    icon: <Flame className="h-4 w-4" />,
  },
  steady: {
    label: "Steady",
    message: "At least one application in the last 7 days.",
    chip: "bg-teal-500/10 text-teal-300 ring-teal-500/30",
    icon: <Activity className="h-4 w-4" />,
  },
  stale: {
    label: "Stale",
    message:
      "No new applications in the last 7 days. Consider tightening the JD or refreshing the skills list — the Insights tab has concrete fixes.",
    chip: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
    icon: <Gauge className="h-4 w-4" />,
  },
  idle: {
    label: "Idle",
    message: "No applicants yet — publish and promote this posting to start receiving them.",
    chip: "bg-zinc-500/10 text-zinc-300 ring-zinc-500/30",
    icon: <Users className="h-4 w-4" />,
  },
};

const CONVERSION_ROWS: {
  key: keyof PostingPerformance["conversion"];
  label: string;
  bar: string;
}[] = [
  { key: "viewed_rate", label: "Viewed or beyond", bar: "bg-sky-400" },
  { key: "shortlist_rate", label: "Shortlisted or beyond", bar: "bg-teal-400" },
  { key: "interview_rate", label: "Interview or beyond", bar: "bg-amber-400" },
  { key: "offer_rate", label: "Offer", bar: "bg-emerald-400" },
  { key: "rejection_rate", label: "Rejected", bar: "bg-rose-400" },
];

function Kpi({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
        {icon} {label}
      </div>
      <div className="mt-2 text-2xl font-bold text-zinc-100">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-zinc-500">{hint}</div>}
    </div>
  );
}

export default function PerformancePage() {
  const params = useParams();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [perf, setPerf] = useState<PostingPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!jobId || !token) return;
    try {
      setError(null);
      setPerf(await getPostingPerformance(jobId, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load performance");
    } finally {
      setLoading(false);
    }
  }, [jobId, token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (authLoading || !ready) return <EmployerLoading />;

  const health = perf ? HEALTH[perf.health] : null;
  const series = perf?.series ?? [];
  const maxCount = Math.max(...series.map((d) => d.count), 1);
  const totalInSeries = series.reduce((s, d) => s + d.count, 0);

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
          <BarChart3 className="h-4 w-4" />
          Performance
        </div>
        <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
          {loading ? "Loading…" : perf?.title ?? "Posting"}
        </h1>
      </div>

      <div className="mt-4">
        <PostingTabs jobId={jobId} active="performance" />
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="mt-6 h-72 animate-pulse rounded-xl bg-zinc-900/50" />
      ) : (
        perf && (
          <>
            {/* ---------- Health banner ---------- */}
            <div
              className={`mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-5 py-4`}
            >
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ring-1 ring-inset ${health?.chip}`}
              >
                {health?.icon}
                {health?.label}
              </span>
              <p className="min-w-0 flex-1 text-sm text-zinc-400">{health?.message}</p>
            </div>

            {/* ---------- KPIs ---------- */}
            <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Kpi
                label="Total applicants"
                value={String(perf.total)}
                icon={<Users className="h-3.5 w-3.5" />}
              />
              <Kpi
                label="Last 7 days"
                value={String(perf.recent_7d)}
                icon={<TrendingUp className="h-3.5 w-3.5" />}
              />
              <Kpi
                label="Days since last apply"
                value={
                  perf.days_since_last_application != null
                    ? String(perf.days_since_last_application)
                    : "—"
                }
                icon={<CalendarClock className="h-3.5 w-3.5" />}
              />
              <Kpi
                label="Avg days to stage move"
                value={perf.avg_days_to_last_move != null ? `${perf.avg_days_to_last_move}` : "—"}
                hint="apply → latest stage change"
                icon={<Timer className="h-3.5 w-3.5" />}
              />
            </div>

            {/* ---------- 30-day chart ---------- */}
            <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                  <Activity className="h-4 w-4 text-teal-400" />
                  Applications — last 30 days
                </div>
                <span className="text-xs text-zinc-500">
                  {totalInSeries} in window · peak {maxCount}/day
                </span>
              </div>

              <div className="mt-5 flex h-36 items-end gap-[3px]">
                {series.map((d) => {
                  const h = d.count === 0 ? 2 : Math.max(6, Math.round((d.count / maxCount) * 100));
                  return (
                    <div
                      key={d.date}
                      title={`${d.date}: ${d.count} application${d.count === 1 ? "" : "s"}`}
                      className={`flex-1 rounded-t transition-all ${
                        d.count === 0 ? "bg-zinc-800" : "bg-gradient-to-t from-teal-600 to-teal-400"
                      }`}
                      style={{ height: `${h}%` }}
                    />
                  );
                })}
              </div>
              <div className="mt-2 flex justify-between text-[10px] text-zinc-600">
                <span>{series[0]?.date}</span>
                <span>{series[Math.floor(series.length / 2)]?.date}</span>
                <span>{series[series.length - 1]?.date}</span>
              </div>

              {totalInSeries === 0 && (
                <p className="mt-3 text-xs text-zinc-500">
                  Nothing in this window yet. Applicants from earlier than 30 days still count in
                  your totals above.
                </p>
              )}
            </div>

            {/* ---------- Conversion ---------- */}
            <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <TrendingUp className="h-4 w-4 text-teal-400" />
                Stage conversion
              </div>

              {perf.total === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  Conversion rates appear once this posting has applicants.
                </p>
              ) : (
                <>
                  <div className="mt-4 space-y-2.5">
                    {CONVERSION_ROWS.map((row) => {
                      const value = perf.conversion[row.key];
                      return (
                        <div key={row.key} className="grid grid-cols-[150px_1fr_52px] items-center gap-3">
                          <span className="text-xs text-zinc-400">{row.label}</span>
                          <span className="h-2.5 overflow-hidden rounded-full bg-zinc-800/80">
                            <span
                              className={`block h-full rounded-full ${row.bar}`}
                              style={{ width: `${Math.max(value, 0)}%` }}
                            />
                          </span>
                          <span className="text-right text-xs font-semibold tabular-nums text-zinc-200">
                            {value}%
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <p className="mt-4 text-[11px] text-zinc-600">
                    Rates are share of all {perf.total} applicant{perf.total === 1 ? "" : "s"}.
                    Rejected is a side state, so the rungs above it don&apos;t sum to 100%.
                  </p>
                </>
              )}
            </div>
          </>
        )
      )}
    </div>
  );
}
