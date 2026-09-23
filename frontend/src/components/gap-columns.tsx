"use client";

import { AlertCircle, ArrowRight, CheckCircle2, MoveRight, Shuffle } from "lucide-react";
import { GapResponse, GapStatus } from "@/lib/types";

// Four-column skill gap view (plan §8): STRONG / PARTIAL / TRANSFERABLE / MISSING,
// each chip carrying its evidence string so every claim stays traceable.
const COLUMNS: {
  status: GapStatus;
  label: string;
  icon: typeof CheckCircle2;
  chip: string;
  ring: string;
}[] = [
  {
    status: "STRONG",
    label: "Strong",
    icon: CheckCircle2,
    chip: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    ring: "border-emerald-500/20",
  },
  {
    status: "PARTIAL",
    label: "Partial",
    icon: ArrowRight,
    chip: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
    ring: "border-cyan-500/20",
  },
  {
    status: "TRANSFERABLE",
    label: "Transferable",
    icon: Shuffle,
    chip: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    ring: "border-violet-500/20",
  },
  {
    status: "MISSING",
    label: "Missing",
    icon: AlertCircle,
    chip: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    ring: "border-amber-500/20",
  },
];

function evidenceDetail(reason?: string, evidence?: Record<string, unknown>): string {
  const parts: string[] = [];
  if (evidence?.proficiency) parts.push(`level: ${String(evidence.proficiency)}`);
  if (typeof evidence?.years === "number") parts.push(`${evidence.years}y experience`);
  if (typeof evidence?.transfer_similarity === "number") {
    parts.push(`transfer sim ${evidence.transfer_similarity}`);
  }
  if (evidence?.via_skill) parts.push(`via ${String(evidence.via_skill)}`);
  return parts.length ? `${reason ?? ""} (${parts.join(", ")})` : (reason ?? "");
}

export function GapColumns({ gap }: { gap: GapResponse }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        const items = gap.classes.filter((c) => c.status === col.status);
        const Icon = col.icon;
        return (
          <div
            key={col.status}
            className={`rounded-2xl border bg-zinc-900/50 p-4 ${col.ring}`}
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-300">
                <Icon className={`h-4 w-4 ${col.chip.split(" ").pop()}`} />
                {col.label}
              </span>
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs font-bold text-zinc-300">
                {items.length}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {items.length === 0 ? (
                <span className="text-xs text-zinc-600">—</span>
              ) : (
                items.map((item) => (
                  <div
                    key={item.skill}
                    title={evidenceDetail(item.evidence.reason, item.evidence)}
                    className={`flex items-center justify-between rounded-lg border px-2.5 py-1.5 text-xs font-medium ${col.chip}`}
                  >
                    <span className="truncate">{item.skill}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
