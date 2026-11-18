import Link from "next/link";
import { AlertCircle, ArrowRightLeft, BarChart3, CheckCircle2, Route } from "lucide-react";
import { SkillDemand, SkillGapSummary as SkillGapSummaryData } from "@/lib/types";

const pct = (share: number) => Math.round(Math.max(0, Math.min(1, share)) * 100);

function matchTone(score: number): string {
  if (score >= 70) return "bg-emerald-500/10 text-emerald-300";
  if (score >= 40) return "bg-amber-500/10 text-amber-300";
  return "bg-rose-500/10 text-rose-300";
}

/** "Docker · 12/20" chip with a thin share bar underneath. */
function MissingChip({ demand, total }: { demand: SkillDemand; total: number }) {
  return (
    <Link
      href="/roadmap"
      title={`${demand.skill} is asked for by ${demand.jobs} of ${total} results (${pct(demand.share)}%) — plan it on your roadmap`}
      className="group inline-flex min-w-[7.5rem] flex-col gap-1 rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-300 transition-colors hover:border-amber-500/40 hover:bg-amber-500/15"
    >
      <span className="flex items-center justify-between gap-2">
        <span className="truncate">{demand.skill}</span>
        <span className="shrink-0 tabular-nums text-amber-400/90">
          {demand.jobs}/{total}
        </span>
      </span>
      <span className="h-1 w-full overflow-hidden rounded-full bg-zinc-800">
        <span
          className="block h-full rounded-full bg-amber-400"
          style={{ width: `${pct(demand.share)}%` }}
        />
      </span>
    </Link>
  );
}

function SmallChips({
  items,
  total,
  className,
}: {
  items: SkillDemand[];
  total: number;
  className: string;
}) {
  return (
    <>
      {items.map((d) => (
        <span
          key={d.skill}
          title={`${d.jobs} of ${total} results (${pct(d.share)}%)`}
          className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${className}`}
        >
          {d.skill}
          <span className="ml-1 tabular-nums opacity-70">
            {d.jobs}/{total}
          </span>
        </span>
      ))}
    </>
  );
}

/**
 * Skill disparity across a whole result set (search, AI search, feed).
 * Renders nothing when the backend returned no summary.
 */
export default function SkillGapSummary({
  summary,
  className = "",
}: {
  summary: SkillGapSummaryData | null | undefined;
  className?: string;
}) {
  if (!summary || summary.jobs_analyzed === 0) return null;
  const total = summary.jobs_analyzed;
  const { top_missing, top_transferable, top_matched } = summary;
  if (
    !summary.headline &&
    top_missing.length + top_transferable.length + top_matched.length === 0
  ) {
    return null;
  }

  return (
    <section
      aria-label="Skill gap across these results"
      className={`rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5 shadow-md ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-teal-400">
            <BarChart3 className="h-3.5 w-3.5" />
            Skill gap across these results
          </span>
          <span className="rounded-full bg-zinc-800/80 px-2 py-0.5 text-[10px] font-semibold text-zinc-300">
            {total} job{total === 1 ? "" : "s"} analysed
          </span>
          {typeof summary.avg_skill_match === "number" && (
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${matchTone(summary.avg_skill_match)}`}
            >
              {Math.round(summary.avg_skill_match)}% avg skill match
            </span>
          )}
        </div>
        {top_missing.length > 0 && (
          <Link
            href="/roadmap"
            className="inline-flex items-center gap-1 text-xs font-semibold text-teal-400 underline-offset-4 hover:text-teal-300 hover:underline"
          >
            <Route className="h-3.5 w-3.5" />
            Plan these on your roadmap
          </Link>
        )}
      </div>

      {summary.headline && (
        <p className="mt-2 text-sm leading-relaxed text-zinc-200">{summary.headline}</p>
      )}

      <div className="mt-3 space-y-2.5">
        {top_missing.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 inline-flex items-center gap-1 text-[11px] font-medium text-amber-400">
              <AlertCircle className="h-3 w-3" /> Most-requested skills you&apos;re missing
            </span>
            {top_missing.map((d) => (
              <MissingChip key={d.skill} demand={d} total={total} />
            ))}
          </div>
        )}

        {top_transferable.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 inline-flex items-center gap-1 text-[11px] font-medium text-sky-400">
              <ArrowRightLeft className="h-3 w-3" /> Transferable
            </span>
            <SmallChips
              items={top_transferable}
              total={total}
              className="border-sky-500/20 bg-sky-500/10 text-sky-300"
            />
          </div>
        )}

        {top_matched.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400">
              <CheckCircle2 className="h-3 w-3" /> You already have
            </span>
            <SmallChips
              items={top_matched}
              total={total}
              className="border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
            />
          </div>
        )}
      </div>
    </section>
  );
}
