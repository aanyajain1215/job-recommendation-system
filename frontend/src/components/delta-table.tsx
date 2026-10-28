"use client";

import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Crown,
  Minus,
  Sparkles,
  Target,
} from "lucide-react";
import { ResultDelta } from "@/lib/types";

function bandChip(band: string): string {
  switch (band) {
    case "high":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "medium":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";
    default:
      return "border-zinc-600 bg-zinc-800 text-zinc-300";
  }
}

function DeltaValue({ delta }: { delta: number }) {
  if (delta > 0.005) {
    return (
      <span className="inline-flex items-center gap-0.5 font-semibold text-emerald-400">
        <ArrowUpRight className="h-3.5 w-3.5" />+{delta.toFixed(1)}
      </span>
    );
  }
  if (delta < -0.005) {
    return (
      <span className="inline-flex items-center gap-0.5 font-semibold text-rose-400">
        <ArrowDownRight className="h-3.5 w-3.5" />
        {delta.toFixed(1)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-zinc-500">
      <Minus className="h-3.5 w-3.5" />
      0.0
    </span>
  );
}

// What-If result table (plan §10): before → after per candidate, band flips,
// eligibility crossings, plus the target-role and per-skill counterfactuals.
export function DeltaTable({ result }: { result: ResultDelta }) {
  const rows = [...result.deltas].sort((a, b) => b.delta - a.delta || a.job_title.localeCompare(b.job_title));
  const improved = rows.filter((r) => r.delta > 0.005).length;
  const eligibleFlips = rows.filter((r) => r.newly_eligible).length;

  return (
    <div className="space-y-5">
      {/* Aggregate before / after */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
            Mean score · before
          </span>
          <div className="mt-1 text-2xl font-black text-zinc-300">
            {result.before.mean_score}
          </div>
          <div className="mt-1 flex gap-1.5 text-[10px]">
            {Object.entries(result.before.band_counts).map(([band, n]) => (
              <span key={band} className={`rounded border px-1.5 py-0.5 ${bandChip(band)}`}>
                {band} {n}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-teal-500/30 bg-teal-500/5 p-4">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-teal-400">
            Mean score · after
          </span>
          <div className="mt-1 text-2xl font-black text-teal-300">
            {result.after.mean_score}
          </div>
          <div className="mt-1 flex gap-1.5 text-[10px]">
            {Object.entries(result.after.band_counts).map(([band, n]) => (
              <span key={band} className={`rounded border px-1.5 py-0.5 ${bandChip(band)}`}>
                {band} {n}
              </span>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
            Impact
          </span>
          <div className="mt-1 space-y-1 text-sm text-zinc-300">
            <div className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-teal-400" />
              {improved} of {rows.length} candidates improved
            </div>
            <div className="flex items-center gap-1.5">
              <Crown className="h-3.5 w-3.5 text-amber-400" />
              {eligibleFlips} newly high-readiness
            </div>
          </div>
        </div>
      </div>

      {/* Target role + per-skill counterfactuals */}
      {result.target && (
        <div className="rounded-2xl border border-teal-500/25 bg-zinc-900/60 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <span className="flex items-center gap-2 text-sm font-bold text-zinc-100">
              <Target className="h-4 w-4 text-teal-400" />
              Target role: {result.target.job_title}
            </span>
            <span className="flex items-center gap-2 text-sm">
              <span className="rounded-full border border-zinc-700 bg-zinc-800 px-2.5 py-0.5 text-xs font-semibold text-zinc-300">
                {result.target.before}%
              </span>
              <span className="text-zinc-600">→</span>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-bold text-emerald-300">
                {result.target.after}%
              </span>
              <DeltaValue delta={result.target.delta} />
            </span>
          </div>

          {result.target.per_skill.length > 0 && (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                If you added each skill on its own
              </span>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {result.target.per_skill.map((entry) => (
                  <div
                    key={entry.skill}
                    className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2"
                  >
                    <span className="text-xs font-medium text-zinc-300">{entry.skill}</span>
                    <span className="flex items-center gap-1.5">
                      <span className="text-xs font-bold text-zinc-100">{entry.score}%</span>
                      <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${bandChip(entry.band)}`}>
                        {entry.band}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Per-candidate delta table */}
      <div className="overflow-x-auto rounded-2xl border border-zinc-800 bg-zinc-900/60">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-zinc-800 text-[10px] uppercase tracking-wider text-zinc-500">
              <th className="px-4 py-3 font-semibold">Job</th>
              <th className="px-4 py-3 font-semibold">Before</th>
              <th className="px-4 py-3 font-semibold">After</th>
              <th className="px-4 py-3 font-semibold">Δ</th>
              <th className="px-4 py-3 font-semibold">Band</th>
              <th className="px-4 py-3 font-semibold">Eligibility</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.job_id}
                className="border-b border-zinc-800/60 last:border-0 hover:bg-zinc-800/30"
              >
                <td className="max-w-[240px] truncate px-4 py-2.5 font-medium text-zinc-200">
                  {row.job_title}
                </td>
                <td className="px-4 py-2.5 text-zinc-400">{row.before}%</td>
                <td className="px-4 py-2.5 text-zinc-200">{row.after}%</td>
                <td className="px-4 py-2.5">
                  <DeltaValue delta={row.delta} />
                </td>
                <td className="px-4 py-2.5">
                  <span className="flex items-center gap-1">
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${bandChip(row.band_before)}`}>
                      {row.band_before}
                    </span>
                    {row.band_changed && (
                      <>
                        <span className="text-zinc-600">→</span>
                        <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${bandChip(row.band_after)}`}>
                          {row.band_after}
                        </span>
                      </>
                    )}
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  {row.newly_eligible && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                      <Sparkles className="h-3 w-3" /> Newly eligible
                    </span>
                  )}
                  {row.lost && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-bold text-rose-300">
                      <AlertTriangle className="h-3 w-3" /> Lost high band
                    </span>
                  )}
                  {!row.newly_eligible && !row.lost && (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
