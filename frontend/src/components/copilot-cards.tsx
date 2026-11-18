import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  ArrowRightLeft,
  Bookmark,
  Building2,
  CheckCircle2,
  ExternalLink,
  FileText,
  ListChecks,
  MapPin,
  Sparkles,
  Target,
  Wallet,
  Wifi,
} from "lucide-react";
import SkillGapSummary from "@/components/skill-gap-summary";
import { TargetCard } from "@/components/direction-gap";
import {
  CopilotApplicationsCard,
  CopilotCard,
  CopilotGapCard,
  CopilotJobCard,
  CopilotResumeCard,
} from "@/lib/types";

const KNOWN_CARD_TYPES = new Set([
  "job",
  "skill_gap_summary",
  "direction_gap",
  "gap",
  "applications",
  "resume",
]);

/** Drop card types this UI doesn't render (the backend may add new ones). */
export function knownCards(cards: unknown): CopilotCard[] {
  if (!Array.isArray(cards)) return [];
  return cards.filter(
    (c): c is CopilotCard =>
      !!c && typeof c === "object" && KNOWN_CARD_TYPES.has((c as { type?: string }).type ?? ""),
  );
}

function scoreTone(score: number) {
  if (score >= 70) return "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30";
  if (score >= 40) return "bg-amber-500/10 text-amber-300 ring-amber-500/30";
  return "bg-rose-500/10 text-rose-300 ring-rose-500/30";
}

const isExternalJob = (card: CopilotJobCard) =>
  card.id.startsWith("live:") || card.source === "adzuna";

function Chips({
  items,
  max,
  className,
}: {
  items: string[];
  max: number;
  className: string;
}) {
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return (
    <>
      {shown.map((skill) => (
        <span
          key={skill}
          className={`rounded-md border px-1.5 py-0.5 text-[10.5px] font-medium ${className}`}
        >
          {skill}
        </span>
      ))}
      {rest > 0 && (
        <span className="rounded-md bg-zinc-800/80 px-1.5 py-0.5 text-[10.5px] text-zinc-400">
          +{rest}
        </span>
      )}
    </>
  );
}

function JobCard({ card }: { card: CopilotJobCard }) {
  const external = isExternalJob(card);
  const matched = card.matched_skills ?? [];
  const missing = card.missing_skills ?? [];
  const transferable = card.transferable_skills ?? [];
  const href = external ? card.url : `/jobs/${card.id}`;

  return (
    <article className="flex w-[17rem] shrink-0 snap-start flex-col rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-4 shadow-md transition-colors hover:border-zinc-700 sm:w-72">
      <div className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1 text-[11px] font-semibold text-zinc-400">
          <Building2 className="h-3 w-3 shrink-0 text-zinc-500" />
          <span className="truncate">{card.company || "Unknown company"}</span>
        </span>
        {typeof card.match_score === "number" && (
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold ring-1 ${scoreTone(card.match_score)}`}
          >
            <Sparkles className="h-2.5 w-2.5" />
            {Math.min(100, Math.round(card.match_score))}% match
          </span>
        )}
      </div>

      <h4 className="mt-1.5 line-clamp-2 text-sm font-bold leading-snug text-zinc-100">
        {card.title}
      </h4>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-zinc-500">
        {card.location && (
          <span className="flex min-w-0 items-center gap-1">
            <MapPin className="h-3 w-3 shrink-0" />
            <span className="max-w-[10rem] truncate">{card.location}</span>
          </span>
        )}
        {card.is_remote && (
          <span className="inline-flex items-center gap-1 text-teal-300">
            <Wifi className="h-3 w-3" /> Remote
          </span>
        )}
        {card.salary && (
          <span className="inline-flex items-center gap-1 text-zinc-300">
            <Wallet className="h-3 w-3 text-emerald-400" /> {card.salary}
          </span>
        )}
        {external && (
          <span className="inline-flex items-center gap-1 text-sky-300">
            <ExternalLink className="h-2.5 w-2.5" /> Live
          </span>
        )}
      </div>

      {(matched.length > 0 || transferable.length > 0 || missing.length > 0) && (
        <div className="mt-3 space-y-1.5 border-t border-zinc-800/60 pt-3">
          {typeof card.skill_match === "number" && (
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              {Math.round(card.skill_match)}% skill match
            </p>
          )}
          {matched.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <CheckCircle2 className="h-3 w-3 text-emerald-400" aria-label="Matched" />
              <Chips
                items={matched}
                max={4}
                className="border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
              />
            </div>
          )}
          {transferable.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <ArrowRightLeft className="h-3 w-3 text-sky-400" aria-label="Transferable" />
              <Chips
                items={transferable}
                max={3}
                className="border-sky-500/20 bg-sky-500/10 text-sky-300"
              />
            </div>
          )}
          {missing.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <AlertCircle className="h-3 w-3 text-amber-400" aria-label="Missing" />
              <Chips
                items={missing}
                max={4}
                className="border-amber-500/20 bg-amber-500/10 text-amber-300"
              />
            </div>
          )}
        </div>
      )}

      {card.reasons?.length > 0 && (
        <ul className="mt-2.5 space-y-0.5">
          {card.reasons.slice(0, 2).map((r) => (
            <li key={r} className="line-clamp-2 text-[11px] leading-relaxed text-zinc-400">
              · {r}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-auto flex items-center gap-2 pt-3">
        {external ? (
          href ? (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-300 ring-1 ring-teal-500/30 transition-colors hover:bg-teal-500/20"
            >
              Open posting <ExternalLink className="h-3 w-3" />
            </a>
          ) : (
            <span className="flex-1 text-center text-[11px] text-zinc-500">Link unavailable</span>
          )
        ) : (
          <>
            <Link
              href={`/jobs/${card.id}`}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-300 ring-1 ring-teal-500/30 transition-colors hover:bg-teal-500/20"
            >
              View job <ArrowRight className="h-3 w-3" />
            </Link>
            <Link
              href={`/gap/${card.id}`}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-zinc-700 hover:text-zinc-100"
            >
              <Target className="h-3 w-3" /> Skill gap
            </Link>
          </>
        )}
      </div>
    </article>
  );
}

const GAP_STATUS_STYLE: Record<string, string> = {
  STRONG: "border-emerald-500/20 bg-emerald-500/10 text-emerald-300",
  PARTIAL: "border-teal-500/20 bg-teal-500/10 text-teal-300",
  TRANSFERABLE: "border-sky-500/20 bg-sky-500/10 text-sky-300",
  MISSING: "border-amber-500/20 bg-amber-500/10 text-amber-300",
};

function GapCard({ card }: { card: CopilotGapCard }) {
  const readiness =
    typeof card.readiness === "number"
      ? { value: card.readiness, band: null as string | null }
      : card.readiness
        ? { value: card.readiness.value, band: card.readiness.band as string | null }
        : null;
  const pct = readiness ? Math.round(readiness.value) : null;
  const counts = card.counts ?? {};

  return (
    <div className="w-full rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-teal-400">
            Skill gap
          </p>
          <h4 className="mt-0.5 truncate text-sm font-bold text-zinc-100">{card.title}</h4>
        </div>
        <div className="flex shrink-0 gap-3 text-right">
          {typeof card.match_score === "number" && (
            <div>
              <p className="text-base font-black text-zinc-100">{Math.round(card.match_score)}%</p>
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">match</p>
            </div>
          )}
          {pct !== null && (
            <div>
              <p className={`text-base font-black ${pct >= 70 ? "text-emerald-300" : pct >= 40 ? "text-amber-300" : "text-rose-300"}`}>
                {pct}%
              </p>
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                ready{readiness?.band ? ` · ${readiness.band}` : ""}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5 text-[10.5px]">
        {(["strong", "partial", "transferable", "missing"] as const).map((k) =>
          typeof counts[k] === "number" ? (
            <span
              key={k}
              className={`rounded-full border px-2 py-0.5 font-semibold capitalize ${GAP_STATUS_STYLE[k.toUpperCase()]}`}
            >
              {counts[k]} {k}
            </span>
          ) : null,
        )}
      </div>

      {card.skills?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {card.skills.slice(0, 12).map((s) => (
            <span
              key={s.skill}
              title={s.status.toLowerCase()}
              className={`rounded-md border px-1.5 py-0.5 text-[10.5px] font-medium ${
                GAP_STATUS_STYLE[s.status.toUpperCase()] ?? "border-zinc-700 bg-zinc-800/60 text-zinc-300"
              }`}
            >
              {s.skill}
            </span>
          ))}
        </div>
      )}

      {card.weakest_link && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-zinc-300">
          <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
          Weakest link: <span className="font-semibold text-amber-300">{card.weakest_link}</span>
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href={`/gap/${card.job_id}`}
          className="inline-flex items-center gap-1 rounded-lg bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-300 ring-1 ring-teal-500/30 hover:bg-teal-500/20"
        >
          Full gap analysis <ArrowRight className="h-3 w-3" />
        </Link>
        <Link
          href={`/jobs/${card.job_id}`}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:border-zinc-700 hover:text-zinc-100"
        >
          View job
        </Link>
      </div>
    </div>
  );
}

const APP_STATUS_STYLE: Record<string, string> = {
  saved: "bg-zinc-500/10 text-zinc-300 ring-zinc-500/30",
  applied: "bg-cyan-500/10 text-cyan-300 ring-cyan-500/30",
  shortlisted: "bg-teal-500/10 text-teal-300 ring-teal-500/30",
  interview: "bg-indigo-500/10 text-indigo-300 ring-indigo-500/30",
  offer: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  rejected: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};

function ApplicationsCard({ card }: { card: CopilotApplicationsCard }) {
  const items = card.items ?? [];
  return (
    <div className="w-full rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-teal-400">
          <ListChecks className="h-3.5 w-3.5" /> Your tracked jobs
        </p>
        <Link href="/tracker" className="text-xs font-semibold text-teal-400 hover:underline">
          Open tracker
        </Link>
      </div>
      {items.length === 0 ? (
        <p className="mt-2 text-xs text-zinc-500">Nothing tracked yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-zinc-800/60">
          {items.slice(0, 10).map((it) => (
            <li key={it.job_id} className="flex items-center justify-between gap-3 py-2">
              <Link href={`/jobs/${it.job_id}`} className="group min-w-0">
                <p className="truncate text-sm font-medium text-zinc-200 group-hover:text-teal-300">
                  {it.title}
                </p>
                <p className="truncate text-[11px] text-zinc-500">
                  {it.company}
                  {it.updated ? ` · ${it.updated}` : ""}
                </p>
              </Link>
              <span
                className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold capitalize ring-1 ring-inset ${
                  APP_STATUS_STYLE[it.status] ?? APP_STATUS_STYLE.saved
                }`}
              >
                {it.status === "saved" && <Bookmark className="h-2.5 w-2.5" />}
                {it.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const SUGGESTION_LABELS: Record<string, string> = {
  bullet: "Original",
  rewrite: "Suggested rewrite",
  issues: "Issues",
  status: "Status",
};

function ResumeCard({ card }: { card: CopilotResumeCard }) {
  const atsScore = typeof card.ats?.ats_score === "number" ? card.ats.ats_score : null;
  const missingKeywords = Array.isArray(card.ats?.missing_keywords)
    ? (card.ats.missing_keywords as unknown[]).filter((k): k is string => typeof k === "string")
    : [];
  const suggestions = Array.isArray(card.suggestions) ? card.suggestions : [];

  return (
    <div className="w-full rounded-xl border border-zinc-800/80 bg-zinc-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-teal-400">
            <FileText className="h-3.5 w-3.5" /> Resume tailoring
          </p>
          <h4 className="mt-0.5 truncate text-sm font-bold text-zinc-100">{card.job_title}</h4>
        </div>
        {atsScore !== null && (
          <div className="shrink-0 text-right">
            <p className="text-base font-black text-zinc-100">{Math.round(atsScore)}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">ATS score</p>
          </div>
        )}
      </div>

      {missingKeywords.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1">
          <span className="mr-1 text-[11px] font-medium text-amber-400">Missing keywords</span>
          <Chips
            items={missingKeywords}
            max={8}
            className="border-amber-500/20 bg-amber-500/10 text-amber-300"
          />
        </div>
      )}

      {suggestions.length > 0 ? (
        <ol className="mt-3 space-y-2">
          {suggestions.map((s, i) => (
            <li key={i} className="rounded-lg border border-zinc-800/60 bg-zinc-950/40 p-3">
              {Object.entries(s).map(([key, value]) => {
                const text = Array.isArray(value)
                  ? value.filter((v) => typeof v === "string" || typeof v === "number").join(" · ")
                  : typeof value === "string" || typeof value === "number"
                    ? String(value)
                    : "";
                if (!text) return null;
                return (
                  <p key={key} className="text-xs leading-relaxed text-zinc-300">
                    <span className="mr-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                      {SUGGESTION_LABELS[key] ?? key.replace(/_/g, " ")}
                    </span>
                    <span className={key === "rewrite" ? "text-teal-200" : undefined}>{text}</span>
                  </p>
                );
              })}
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">No bullet rewrites suggested.</p>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        {card.disclaimer && (
          <p className="text-[11px] leading-relaxed text-zinc-500">{card.disclaimer}</p>
        )}
        <Link
          href="/resume-optimize"
          className="inline-flex items-center gap-1 text-xs font-semibold text-teal-400 hover:underline"
        >
          Open resume optimizer <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}

/** Renders the structured results attached to one assistant turn. */
export function CopilotCards({ cards }: { cards: CopilotCard[] }) {
  if (cards.length === 0) return null;
  const jobs = cards.filter((c): c is CopilotJobCard => c.type === "job");
  const others = cards.filter((c) => c.type !== "job");

  return (
    <div className="mt-2 space-y-2.5">
      {jobs.length > 0 && (
        <div className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 [scrollbar-width:thin]">
          {jobs.map((card) => (
            <JobCard key={card.id} card={card} />
          ))}
        </div>
      )}
      {others.map((card, i) => {
        switch (card.type) {
          case "skill_gap_summary":
            return <SkillGapSummary key={`sgs-${i}`} summary={card} />;
          case "direction_gap":
            return <TargetCard key={`dg-${card.kind}-${card.target}`} gap={card} />;
          case "gap":
            return <GapCard key={`gap-${card.job_id}-${i}`} card={card} />;
          case "applications":
            return <ApplicationsCard key={`apps-${i}`} card={card} />;
          case "resume":
            return <ResumeCard key={`resume-${card.job_id}-${i}`} card={card} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
