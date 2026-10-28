"use client";

import { AlertCircle, CheckCircle2, Lightbulb, Target, Zap } from "lucide-react";
import { GapResponse } from "@/lib/types";

// Deterministic explanation card (plan §12): every number shown comes from
// the engine response — this component only arranges evidence, it never
// computes or invents a score.
export function ExplanationCard({ gap }: { gap: GapResponse }) {
  const strengths = gap.classes.filter(
    (c) => c.status === "STRONG" || c.status === "TRANSFERABLE",
  );
  const concerns = gap.classes.filter(
    (c) => c.status === "MISSING" || c.status === "PARTIAL",
  );

  const recommendedAction = gap.weakest_link
    ? `Build one small project using ${gap.weakest_link} and add it to your profile — that converts your biggest gap into demonstrated evidence.`
    : gap.missing_required.length === 0
      ? "Apply — this posting aligns with your current profile."
      : `Close the gap on ${gap.missing_required[0]} first, then re-check your readiness.`;

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5 sm:p-6 shadow-md">
      {/* Headline scores */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-400">
          <Zap className="h-3.5 w-3.5 fill-current" />
          {gap.match_score}% Match
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-300">
          <Target className="h-3.5 w-3.5" />
          Skill match {gap.gap_score}%
        </span>
        <span className="inline-flex items-center rounded-full border border-zinc-700 bg-zinc-800/80 px-3 py-1 text-xs font-semibold text-zinc-300">
          Readiness: {Math.round(gap.readiness.value * 100)}% · {gap.readiness.band}
        </span>
      </div>

      {/* Deterministic reasons (verbatim from the engine) */}
      <ul className="space-y-1.5 mb-4">
        {gap.reasons.map((reason, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-zinc-300">
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-teal-400" />
            <span>{reason}</span>
          </li>
        ))}
      </ul>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Strengths */}
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
          <span className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" /> Strengths
          </span>
          <div className="flex flex-wrap gap-1.5">
            {strengths.length === 0 ? (
              <span className="text-xs text-zinc-500">No strong signals yet</span>
            ) : (
              strengths.map((c) => (
                <span
                  key={c.skill}
                  title={c.evidence.reason}
                  className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-300"
                >
                  {c.skill}
                </span>
              ))
            )}
          </div>
        </div>

        {/* Concerns */}
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
          <span className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-400">
            <AlertCircle className="h-3.5 w-3.5" /> Gaps to close
          </span>
          <div className="flex flex-wrap gap-1.5">
            {concerns.length === 0 ? (
              <span className="text-xs text-zinc-500">Nothing outstanding</span>
            ) : (
              concerns.map((c) => (
                <span
                  key={c.skill}
                  title={c.evidence.reason}
                  className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                    c.status === "MISSING"
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                      : "border-zinc-600/50 bg-zinc-800 text-zinc-300"
                  }`}
                >
                  {c.skill}
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Recommended action — deterministic, first missing required skill wins */}
      <div className="mt-4 flex items-start gap-2 rounded-xl border border-teal-500/20 bg-teal-500/5 p-3 text-sm text-teal-300">
        <Lightbulb className="mt-0.5 h-4 w-4 flex-shrink-0 text-teal-400" />
        <span>{recommendedAction}</span>
      </div>
    </div>
  );
}
