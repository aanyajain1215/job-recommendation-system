"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getPostingTalent } from "@/lib/api";
import { PostingTalent } from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { PostingTabs } from "@/components/posting-tabs";
import { StagePill, fitBand } from "@/components/stage-pill";
import {
  ArrowLeft,
  FileText,
  Lock,
  Mail,
  MapPin,
  Sparkles,
  Target,
  UserSearch,
  Users,
} from "lucide-react";

/** Stable display order for the eight scoring components. */
const COMPONENT_ORDER = [
  "skill",
  "semantic",
  "experience",
  "interest",
  "project",
  "location",
  "salary",
  "education",
];

const COMPONENT_LABELS: Record<string, string> = {
  skill: "Skills",
  semantic: "Semantic fit",
  experience: "Experience",
  interest: "Career interest",
  project: "Projects",
  location: "Location",
  salary: "Salary",
  education: "Education",
};

const COMPONENT_BAR: Record<string, string> = {
  skill: "bg-teal-400",
  semantic: "bg-sky-400",
  experience: "bg-amber-400",
  interest: "bg-indigo-400",
  project: "bg-cyan-400",
  location: "bg-zinc-400",
  salary: "bg-emerald-400",
  education: "bg-purple-400",
};

function initialsOf(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export default function TalentPage() {
  const params = useParams();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [talent, setTalent] = useState<PostingTalent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0);

  const load = useCallback(async () => {
    if (!jobId || !token) return;
    try {
      setError(null);
      setTalent(await getPostingTalent(jobId, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load talent ranking");
    } finally {
      setLoading(false);
    }
  }, [jobId, token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (authLoading || !ready) return <EmployerLoading />;

  const visible = (talent?.candidates ?? []).filter((c) => c.fit_score >= minScore);

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
          <UserSearch className="h-4 w-4" />
          Reverse match
        </div>
        <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
          {loading ? "Loading…" : talent?.title ?? "Posting"}
        </h1>
      </div>

      <div className="mt-4">
        <PostingTabs jobId={jobId} active="talent" />
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
          {/* ---------- Explainer ---------- */}
          <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                  <Sparkles className="h-4 w-4 text-teal-400" />
                  The candidate&apos;s own matching engine, run in reverse
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
                  Each applicant is scored against this posting with the same eight components they
                  see on their side — skills, semantic fit, experience, projects, location, salary
                  and career interest. Scores are assistive ranking only; nothing here rejects
                  anyone automatically.
                </p>
              </div>
              <div className="flex items-center gap-1.5 rounded-lg bg-zinc-950/70 px-3 py-2 text-[11px] font-medium text-zinc-400 ring-1 ring-inset ring-zinc-800">
                <Lock className="h-3.5 w-3.5 text-zinc-500" />
                Only your applicants — no global pool
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-800/70 pt-4 text-xs text-zinc-500">
              <span>
                Ranked <span className="font-semibold text-teal-300">{talent?.scored ?? 0}</span>{" "}
                of {talent?.total_applicants ?? 0} applicant
                {(talent?.total_applicants ?? 0) === 1 ? "" : "s"}
              </span>
              <span className="text-zinc-700">·</span>
              <label className="flex items-center gap-2">
                Minimum fit score
                <input
                  type="range"
                  min={0}
                  max={90}
                  step={5}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  className="h-1 w-28 cursor-pointer appearance-none rounded-full bg-zinc-800 accent-teal-500"
                />
                <span className="w-6 tabular-nums font-semibold text-zinc-300">{minScore}</span>
              </label>
            </div>
          </div>

          {/* ---------- Ranked candidates ---------- */}
          {visible.length === 0 ? (
            <div className="mt-6 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
              <Users className="mx-auto h-8 w-8 text-zinc-600" />
              <p className="mt-3 text-sm font-medium text-zinc-300">
                {(talent?.candidates.length ?? 0) === 0
                  ? "No applicants to rank yet"
                  : "No candidates at or above that fit score"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {(talent?.candidates.length ?? 0) === 0
                  ? "Once people apply, they'll appear here ranked by fit with a full score breakdown."
                  : "Lower the minimum fit score to see more of the pool."}
              </p>
            </div>
          ) : (
            <ol className="mt-4 space-y-3">
              {visible.map((c, i) => {
                const band = fitBand(c.fit_score);
                return (
                  <li
                    key={c.application_id}
                    className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5 transition-colors hover:border-zinc-700/70"
                  >
                    <div className="flex flex-wrap items-start gap-4">
                      {/* rank */}
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-bold text-zinc-400">
                        {i + 1}
                      </div>

                      {/* avatar */}
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400/80 to-cyan-600/80 text-sm font-bold text-zinc-950">
                        {initialsOf(c.name) || "?"}
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-zinc-100">{c.name}</span>
                          <StagePill status={c.status} />
                          {c.years_of_experience != null && (
                            <span className="text-xs text-zinc-500">
                              {c.years_of_experience} yrs
                            </span>
                          )}
                        </div>
                        {c.headline && (
                          <div className="mt-0.5 text-sm text-zinc-400">{c.headline}</div>
                        )}
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
                          {c.location && (
                            <span className="inline-flex items-center gap-1">
                              <MapPin className="h-3 w-3" />
                              {c.location}
                            </span>
                          )}
                          <span>
                            applied {new Date(c.applied_at).toLocaleDateString()}
                          </span>
                          {c.email && (
                            <a
                              href={`mailto:${c.email}`}
                              className="inline-flex items-center gap-1 hover:text-teal-400"
                            >
                              <Mail className="h-3 w-3" />
                              {c.email}
                            </a>
                          )}
                        </div>

                        {/* skills */}
                        <div className="mt-3 space-y-1.5">
                          {c.matched_skills.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                                Matched
                              </span>
                              {c.matched_skills.map((s) => (
                                <span
                                  key={s}
                                  className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[11px] font-medium text-teal-300 ring-1 ring-inset ring-teal-500/30"
                                >
                                  {s}
                                </span>
                              ))}
                            </div>
                          )}
                          {c.missing_required.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
                                Missing
                              </span>
                              {c.missing_required.map((s) => (
                                <span
                                  key={s}
                                  className="rounded-full bg-rose-500/10 px-2 py-0.5 text-[11px] font-medium text-rose-300 ring-1 ring-inset ring-rose-500/30"
                                >
                                  {s}
                                </span>
                              ))}
                            </div>
                          )}
                          {c.transferable.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span
                                title="Adjacent skills (skill2vec) the candidate could transfer into"
                                className="text-[10px] font-semibold uppercase tracking-wider text-zinc-600"
                              >
                                Adjacent
                              </span>
                              {c.transferable.map((s) => (
                                <span
                                  key={s}
                                  title="Adjacent via skill2vec — candidate can transfer into this"
                                  className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-300 ring-1 ring-inset ring-sky-500/30"
                                >
                                  {s}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* fit score */}
                      <div
                        className={`flex shrink-0 flex-col items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-950/60 px-4 py-3 ring-1 ring-inset ${band.ring}`}
                      >
                        <div className={`text-3xl font-bold tabular-nums ${band.text}`}>
                          {c.fit_score.toFixed(1)}
                        </div>
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                          Fit score
                        </div>
                        <div className={`text-[11px] font-medium ${band.text}`}>{band.label}</div>
                      </div>
                    </div>

                    {/* component breakdown */}
                    <div className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 border-t border-zinc-800/70 pt-4 sm:grid-cols-2">
                      {COMPONENT_ORDER.filter((k) => c.components[k] != null).map((k) => {
                        const value = c.components[k];
                        return (
                          <div key={k} className="flex items-center gap-2.5">
                            <span className="w-24 shrink-0 text-[11px] text-zinc-500">
                              {COMPONENT_LABELS[k] ?? k}
                            </span>
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800/80">
                              <span
                                className={`block h-full rounded-full ${COMPONENT_BAR[k] ?? "bg-zinc-400"}`}
                                style={{ width: `${Math.max(2, Math.round(value))}%` }}
                              />
                            </span>
                            <span className="w-8 shrink-0 text-right text-[11px] font-semibold tabular-nums text-zinc-300">
                              {Math.round(value)}
                            </span>
                          </div>
                        );
                      })}
                    </div>

                    {/* actions */}
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      {(c.resume_url || c.email) && (
                        <span className="inline-flex items-center gap-2">
                          {c.resume_url && (
                            <a
                              href={c.resume_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                            >
                              <FileText className="h-3.5 w-3.5" />
                              View resume
                            </a>
                          )}
                        </span>
                      )}
                      <Link
                        href={`/hiring/postings/${jobId}/applicants`}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-400 hover:text-zinc-200"
                      >
                        <Target className="h-3.5 w-3.5" />
                        Move stage in pipeline
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </div>
  );
}
