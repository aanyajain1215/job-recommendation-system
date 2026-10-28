"use client";

import {
  BookOpen,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  Rocket,
} from "lucide-react";
import { RoadmapResponse, RoadmapStep } from "@/lib/types";

// Phase timeline (plan §9): phases pack ≤ 25h each; every skill step can be
// marked complete when the roadmap is persisted (has an id).
export function PhaseTimeline({
  roadmap,
  doneSeqs,
  onComplete,
  completingSeq,
}: {
  roadmap: RoadmapResponse;
  doneSeqs: Set<number>;
  onComplete?: (step: RoadmapStep) => void;
  completingSeq?: number | null;
}) {
  return (
    <div className="space-y-6">
      {roadmap.phases.map((phase, pIdx) => (
        <div key={phase.label} className="relative">
          {/* Connector line */}
          {pIdx < roadmap.phases.length - 1 && (
            <div className="absolute left-[19px] top-12 bottom-[-24px] w-px bg-zinc-800" />
          )}

          {/* Phase header */}
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full border border-teal-500/40 bg-teal-500/10 text-sm font-black text-teal-300">
              {pIdx + 1}
            </div>
            <div>
              <span className="block text-sm font-bold text-zinc-100">{phase.label}</span>
              <span className="flex items-center gap-1 text-xs text-zinc-400">
                <Clock className="h-3 w-3" /> ~{phase.est_hours}h · {phase.steps.length} step
                {phase.steps.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>

          {/* Steps */}
          <div className="ml-5 space-y-2 border-l border-zinc-800 pl-6">
            {phase.steps.map((step) => {
              const done = doneSeqs.has(step.seq);
              const isProject = step.kind === "project";
              const busy = completingSeq === step.seq;
              return (
                <div
                  key={step.seq}
                  className={`group relative rounded-xl border p-3.5 transition-colors ${
                    done
                      ? "border-emerald-500/25 bg-emerald-500/5"
                      : isProject
                        ? "border-violet-500/25 bg-violet-500/5"
                        : "border-zinc-800 bg-zinc-900/60 hover:border-zinc-700"
                  }`}
                >
                  {/* Rail dot */}
                  <span
                    className={`absolute -left-[31px] top-4 flex h-3.5 w-3.5 items-center justify-center rounded-full border-2 ${
                      done
                        ? "border-emerald-400 bg-emerald-400"
                        : "border-zinc-700 bg-zinc-950"
                    }`}
                  />

                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-2.5 min-w-0">
                      {isProject ? (
                        <Rocket className="mt-0.5 h-4 w-4 flex-shrink-0 text-violet-400" />
                      ) : done ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-400" />
                      ) : (
                        <BookOpen className="mt-0.5 h-4 w-4 flex-shrink-0 text-teal-400" />
                      )}
                      <div className="min-w-0">
                        <span
                          className={`block text-sm font-semibold ${
                            done ? "text-zinc-500 line-through" : "text-zinc-100"
                          }`}
                        >
                          {step.title}
                        </span>
                        <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500">
                          <span>#{step.seq}</span>
                          {step.category && (
                            <span className="rounded bg-zinc-800 px-1.5 py-0.5 uppercase tracking-wide text-zinc-300">
                              {step.category}
                            </span>
                          )}
                          {step.est_hours > 0 && <span>~{step.est_hours}h</span>}
                          {isProject && <span>apply · demo</span>}
                        </span>
                      </div>
                    </div>

                    {!isProject && onComplete && roadmap.id && (
                      <button
                        onClick={() => onComplete(step)}
                        disabled={done || busy}
                        className={`inline-flex flex-shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                          done
                            ? "cursor-default border-emerald-500/30 text-emerald-400"
                            : "border-zinc-700 text-zinc-300 hover:border-teal-500/50 hover:text-teal-300"
                        }`}
                      >
                        {busy ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : done ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : (
                          <Circle className="h-3 w-3" />
                        )}
                        {done ? "Done" : "Complete"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
