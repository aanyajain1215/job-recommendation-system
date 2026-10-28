import { ApplicationStatus } from "@/lib/types";

/**
 * Shared pipeline-stage vocabulary (plan §E1/E2): funnel order, labels and
 * chip/bar colors used by the Applicants and Talent tabs.
 */
export const STAGES: {
  key: ApplicationStatus;
  label: string;
  chip: string;
  bar: string;
}[] = [
  { key: "applied", label: "Applied", chip: "bg-zinc-500/10 text-zinc-300 ring-zinc-500/30", bar: "bg-zinc-400" },
  { key: "viewed", label: "Viewed", chip: "bg-sky-500/10 text-sky-300 ring-sky-500/30", bar: "bg-sky-400" },
  { key: "shortlisted", label: "Shortlisted", chip: "bg-teal-500/10 text-teal-300 ring-teal-500/30", bar: "bg-teal-400" },
  { key: "interview", label: "Interview", chip: "bg-amber-500/10 text-amber-300 ring-amber-500/30", bar: "bg-amber-400" },
  { key: "offer", label: "Offer", chip: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30", bar: "bg-emerald-400" },
  { key: "rejected", label: "Rejected", chip: "bg-rose-500/10 text-rose-300 ring-rose-500/30", bar: "bg-rose-400" },
  { key: "saved", label: "Saved", chip: "bg-purple-500/10 text-purple-300 ring-purple-500/30", bar: "bg-purple-400" },
];

export const STAGE_META = Object.fromEntries(
  STAGES.map((s) => [s.key, s]),
) as Record<ApplicationStatus, (typeof STAGES)[number]>;

export function StagePill({ status }: { status: ApplicationStatus }) {
  const s = STAGE_META[status] ?? STAGE_META.applied;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${s.chip}`}
    >
      {s.label}
    </span>
  );
}

/** Color bands for the reverse-match fit score (assistive, 0-100). */
export function fitBand(score: number): { label: string; text: string; ring: string } {
  if (score >= 70)
    return { label: "Strong fit", text: "text-emerald-300", ring: "ring-emerald-500/40" };
  if (score >= 55) return { label: "Good fit", text: "text-teal-300", ring: "ring-teal-500/40" };
  if (score >= 40) return { label: "Partial fit", text: "text-amber-300", ring: "ring-amber-500/40" };
  return { label: "Stretch fit", text: "text-rose-300", ring: "ring-rose-500/40" };
}
