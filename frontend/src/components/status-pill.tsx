import { JobStatus } from "@/lib/types";

const STYLES: Record<JobStatus, { label: string; className: string }> = {
  published: {
    label: "Published",
    className: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  },
  draft: {
    label: "Draft",
    className: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  },
  closed: {
    label: "Closed",
    className: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  },
  archived: {
    label: "Archived",
    className: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30",
  },
};

export function StatusPill({ status }: { status: JobStatus }) {
  const s = STYLES[status] ?? STYLES.draft;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${s.className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {s.label}
    </span>
  );
}
