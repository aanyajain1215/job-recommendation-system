"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import {
  getJobApplicants,
  getPostingPipeline,
  setApplicationStatus,
} from "@/lib/api";
import { ApplicationStatus, EmployerApplication, PostingPipeline } from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { PostingTabs } from "@/components/posting-tabs";
import { STAGES, STAGE_META, StagePill } from "@/components/stage-pill";
import {
  ArrowLeft,
  Calendar,
  ChevronDown,
  ChevronUp,
  FileText,
  Filter,
  Gauge,
  Mail,
  MapPin,
  Phone,
  Search,
  UserCheck,
  Users,
} from "lucide-react";

function initialsOf(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export default function ApplicantsPage() {
  const params = useParams();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [pipeline, setPipeline] = useState<PostingPipeline | null>(null);
  const [apps, setApps] = useState<EmployerApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // filters
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<ApplicationStatus | "all">("all");

  // batch selection
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkStage, setBulkStage] = useState<ApplicationStatus>("shortlisted");

  // per-row cover-note expansion
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    if (!jobId || !token) return;
    try {
      setError(null);
      const [pipe, rows] = await Promise.all([
        getPostingPipeline(jobId, token),
        getJobApplicants(jobId, token),
      ]);
      setPipeline(pipe);
      setApps(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load applicants");
    } finally {
      setLoading(false);
    }
  }, [jobId, token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  /** Single stage move: patch locally, then refresh funnel numbers. */
  const moveStage = async (app: EmployerApplication, next: ApplicationStatus) => {
    if (!token || app.status === next) return;
    setBusyId(app.id);
    try {
      const updated = await setApplicationStatus(app.id, next, token);
      setApps((prev) => prev.map((a) => (a.id === app.id ? { ...a, status: updated.status } : a)));
      const pipe = await getPostingPipeline(jobId, token);
      setPipeline(pipe);
      const who = app.applicant ? `${app.applicant.first_name} ${app.applicant.last_name}`.trim() : "Applicant";
      toast.success(`${who} → ${STAGE_META[next].label}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not move candidate");
    } finally {
      setBusyId(null);
    }
  };

  const runBulkMove = async () => {
    if (!token || selected.size === 0) return;
    const targets = apps.filter((a) => selected.has(a.id) && a.status !== bulkStage);
    if (targets.length === 0) {
      toast.info("Selected candidates are already in that stage.");
      return;
    }
    setBusyId("__bulk__");
    const results = await Promise.allSettled(
      targets.map((a) => setApplicationStatus(a.id, bulkStage, token)),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;
    setSelected(new Set());
    await load();
    if (failed === 0) {
      toast.success(`Moved ${ok} candidate${ok === 1 ? "" : "s"} to ${STAGE_META[bulkStage].label}.`);
    } else {
      toast.warning(`Moved ${ok}, but ${failed} failed.`);
    }
    setBusyId(null);
  };

  // ---- derived ----
  const counts = pipeline?.counts;
  const maxCount = counts ? Math.max(...Object.values(counts), 1) : 1;

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return apps.filter((a) => {
      if (stageFilter !== "all" && a.status !== stageFilter) return false;
      if (!q) return true;
      const p = a.applicant;
      const hay = [
        p ? `${p.first_name} ${p.last_name}` : "",
        p?.headline ?? "",
        p?.location ?? "",
        a.user_email ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [apps, query, stageFilter]);

  const allVisibleSelected =
    visible.length > 0 && visible.every((a) => selected.has(a.id));

  const toggleSelectAll = () => {
    setSelected((prev) => {
      const nextSet = new Set(prev);
      if (allVisibleSelected) visible.forEach((a) => nextSet.delete(a.id));
      else visible.forEach((a) => nextSet.add(a.id));
      return nextSet;
    });
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(id)) nextSet.delete(id);
      else nextSet.add(id);
      return nextSet;
    });
  };

  const toggleNote = (id: string) => {
    setExpanded((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(id)) nextSet.delete(id);
      else nextSet.add(id);
      return nextSet;
    });
  };

  if (authLoading || !ready) return <EmployerLoading />;

  const inputCls =
    "rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none";
  const selectCls =
    "rounded-lg border border-zinc-800 bg-zinc-950/70 px-2.5 py-1.5 text-xs font-medium text-zinc-200 focus:border-teal-500 focus:outline-none";

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <Link
        href={`/hiring/postings/${jobId}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-400 hover:text-zinc-200"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to posting
      </Link>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
            <Users className="h-4 w-4" />
            Applicant pipeline
          </div>
          <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
            {loading ? "Loading…" : pipeline?.title ?? "Posting"}
          </h1>
        </div>
      </div>

      <div className="mt-4">
        <PostingTabs jobId={jobId} active="applicants" />
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
          {/* ---------- Pace strip ---------- */}
          <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
                <Users className="h-3.5 w-3.5" /> Total applicants
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-100">{pipeline?.total ?? 0}</div>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
                <Calendar className="h-3.5 w-3.5" /> Last 7 days
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-100">{pipeline?.recent_7d ?? 0}</div>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
                <Calendar className="h-3.5 w-3.5" /> Days open
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-100">{pipeline?.days_open ?? 0}</div>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-500">
                <Gauge className="h-3.5 w-3.5" /> Pace
              </div>
              <div className="mt-2 text-2xl font-bold text-teal-300">
                {pipeline?.applications_per_day ?? 0}
              </div>
              <div className="text-[11px] text-zinc-500">applicants / day</div>
            </div>
          </div>

          {/* ---------- Funnel ---------- */}
          <div className="mt-6 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
                Funnel
              </h2>
              {stageFilter !== "all" && (
                <button
                  type="button"
                  onClick={() => setStageFilter("all")}
                  className="inline-flex items-center gap-1 text-xs font-medium text-teal-400 hover:text-teal-300"
                >
                  <Filter className="h-3.5 w-3.5" />
                  Clear stage filter
                </button>
              )}
            </div>

            <div className="mt-4 space-y-2">
              {STAGES.map((stage) => {
                const count = counts?.[stage.key] ?? 0;
                const pct = pipeline?.total ? Math.round((count / pipeline.total) * 100) : 0;
                const active = stageFilter === stage.key;
                return (
                  <button
                    key={stage.key}
                    type="button"
                    onClick={() => setStageFilter(active ? "all" : stage.key)}
                    aria-pressed={active}
                    className={`grid w-full grid-cols-[92px_1fr_78px] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors sm:grid-cols-[110px_1fr_92px] ${
                      active ? "bg-teal-500/10 ring-1 ring-inset ring-teal-500/30" : "hover:bg-zinc-800/40"
                    }`}
                  >
                    <span
                      className={`text-xs font-semibold ${active ? "text-teal-300" : "text-zinc-300"}`}
                    >
                      {stage.label}
                    </span>
                    <span className="h-2.5 overflow-hidden rounded-full bg-zinc-800/80">
                      <span
                        className={`block h-full rounded-full ${stage.bar} transition-all`}
                        style={{ width: `${Math.round((count / maxCount) * 100)}%`, opacity: count === 0 ? 0.25 : 1 }}
                      />
                    </span>
                    <span className="text-right text-xs tabular-nums">
                      <span className="font-semibold text-zinc-100">{count}</span>
                      <span className="ml-1.5 text-zinc-500">{pct}%</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="mt-3 text-[11px] text-zinc-600">
              Click a stage to filter the list below. All changes here are assistive — nothing is
              auto-rejected.
            </p>
          </div>

          {/* ---------- Toolbar ---------- */}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <div className="relative flex-1 sm:min-w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search name, headline, location or email…"
                className={`${inputCls} w-full`}
              />
            </div>

            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value as ApplicationStatus | "all")}
              className={selectCls}
            >
              <option value="all">All stages</option>
              {STAGES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>

            <span className="text-xs text-zinc-500">
              {visible.length} of {apps.length}
            </span>
          </div>

          {/* ---------- Bulk bar ---------- */}
          {apps.length > 0 && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-4 py-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleSelectAll}
                  className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 text-teal-500 focus:ring-teal-500"
                />
                Select all visible
                {selected.size > 0 && (
                  <span className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[11px] font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30">
                    {selected.size} selected
                  </span>
                )}
              </label>

              <div className="flex items-center gap-2">
                <select
                  value={bulkStage}
                  onChange={(e) => setBulkStage(e.target.value as ApplicationStatus)}
                  className={selectCls}
                >
                  {STAGES.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={runBulkMove}
                  disabled={selected.size === 0 || busyId === "__bulk__"}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500 px-3 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <UserCheck className="h-3.5 w-3.5" />
                  {busyId === "__bulk__" ? "Moving…" : `Move ${selected.size || ""}`.trim()}
                </button>
              </div>
            </div>
          )}

          {/* ---------- Candidate list ---------- */}
          {visible.length === 0 ? (
            <div className="mt-6 rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
              <Users className="mx-auto h-8 w-8 text-zinc-600" />
              <p className="mt-3 text-sm font-medium text-zinc-300">
                {apps.length === 0 ? "No applicants yet" : "No candidates match this filter"}
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {apps.length === 0
                  ? "When someone applies to this posting, they'll appear here with their fit context."
                  : "Try a different stage or clear the search."}
              </p>
            </div>
          ) : (
            <ul className="mt-4 space-y-3">
              {visible.map((app) => {
                const p = app.applicant;
                const name = p ? `${p.first_name} ${p.last_name}`.trim() : "Unnamed candidate";
                const noteOpen = expanded.has(app.id);
                const isBusy = busyId === app.id;
                return (
                  <li
                    key={app.id}
                    className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 transition-colors hover:border-zinc-700/70"
                  >
                    <div className="flex flex-wrap items-start gap-4">
                      <input
                        type="checkbox"
                        checked={selected.has(app.id)}
                        onChange={() => toggleSelect(app.id)}
                        aria-label={`Select ${name}`}
                        className="mt-1.5 h-4 w-4 shrink-0 rounded border-zinc-700 bg-zinc-900 text-teal-500 focus:ring-teal-500"
                      />

                      {/* avatar */}
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400/80 to-cyan-600/80 text-sm font-bold text-zinc-950">
                        {initialsOf(name) || "?"}
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-zinc-100">{name}</span>
                          <StagePill status={app.status} />
                        </div>

                        {p?.headline && (
                          <div className="mt-0.5 truncate text-sm text-zinc-400">{p.headline}</div>
                        )}

                        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
                          {p?.location && (
                            <span className="inline-flex items-center gap-1">
                              <MapPin className="h-3 w-3" />
                              {p.location}
                            </span>
                          )}
                          {p?.years_of_experience != null && (
                            <span>{p.years_of_experience} yrs experience</span>
                          )}
                          <span className="inline-flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {new Date(app.applied_at).toLocaleDateString()}
                          </span>
                          {app.user_email && (
                            <a
                              href={`mailto:${app.user_email}`}
                              className="inline-flex items-center gap-1 hover:text-teal-400"
                            >
                              <Mail className="h-3 w-3" />
                              {app.user_email}
                            </a>
                          )}
                          {p?.phone && (
                            <span className="inline-flex items-center gap-1">
                              <Phone className="h-3 w-3" />
                              {p.phone}
                            </span>
                          )}
                        </div>

                        {/* cover note (collapsible) */}
                        {app.cover_note && (
                          <div className="mt-2">
                            <button
                              type="button"
                              onClick={() => toggleNote(app.id)}
                              className="inline-flex items-center gap-1 text-xs font-medium text-zinc-400 hover:text-zinc-200"
                            >
                              Cover note
                              {noteOpen ? (
                                <ChevronUp className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                              )}
                            </button>
                            {noteOpen && (
                              <p className="mt-1.5 whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-xs leading-relaxed text-zinc-300">
                                {app.cover_note}
                              </p>
                            )}
                          </div>
                        )}
                      </div>

                      {/* actions */}
                      <div className="flex shrink-0 flex-col items-end gap-2">
                        <select
                          value={app.status}
                          disabled={isBusy}
                          onChange={(e) => moveStage(app, e.target.value as ApplicationStatus)}
                          aria-label={`Stage for ${name}`}
                          className={`${selectCls} disabled:opacity-50`}
                        >
                          {STAGES.map((s) => (
                            <option key={s.key} value={s.key}>
                              {s.label}
                            </option>
                          ))}
                        </select>

                        {(app.resume_url_snapshot || p?.resume_url) && (
                          <a
                            href={(app.resume_url_snapshot || p?.resume_url) as string}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                          >
                            <FileText className="h-3.5 w-3.5" />
                            View resume
                          </a>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
