"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  getJobDetail,
  simulateWhatIf,
  updateJob,
} from "@/lib/api";
import {
  ExperienceLevel,
  JobDetail,
  JobUpdatePayload,
  WhatIfRequest,
  WhatIfResult,
} from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { PostingTabs } from "@/components/posting-tabs";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Gauge,
  RotateCcw,
  Save,
  Sparkles,
  Target,
  Users,
  Wand2,
  Zap,
} from "lucide-react";

const LEVELS: ExperienceLevel[] = ["entry", "mid", "senior", "lead", "executive"];

type RemoteChoice = "keep" | "remote" | "onsite";

function DeltaChip({ value, unit = "" }: { value: number; unit?: string }) {
  const tone =
    value > 0
      ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
      : value < 0
        ? "bg-rose-500/10 text-rose-300 ring-rose-500/30"
        : "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30";
  const label = value > 0 ? `+${value}` : `${value}`;
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${tone}`}
    >
      {label}
      {unit}
    </span>
  );
}

export default function WhatIfPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // relaxation state
  const [drops, setDrops] = useState<Set<string>>(new Set());
  const [expLevel, setExpLevel] = useState<ExperienceLevel | "keep">("keep");
  const [remote, setRemote] = useState<RemoteChoice>("keep");
  const [salMin, setSalMin] = useState("");
  const [salMax, setSalMax] = useState("");

  const [simulating, setSimulating] = useState(false);
  const [applying, setApplying] = useState(false);

  const buildRequest = useCallback(
    (dropsOverride?: Set<string>): WhatIfRequest => {
      const d = dropsOverride ?? drops;
      return {
        drop_required_skills: [...d],
        experience_level: expLevel === "keep" ? null : expLevel,
        is_remote: remote === "keep" ? null : remote === "remote",
        salary_min: salMin === "" ? null : Number(salMin),
        salary_max: salMax === "" ? null : Number(salMax),
      };
    },
    [drops, expLevel, remote, salMin, salMax],
  );

  const runSimulation = useCallback(
    async (override?: WhatIfRequest) => {
      if (!token) return;
      setSimulating(true);
      try {
        setError(null);
        setResult(await simulateWhatIf(jobId, override ?? buildRequest(), token));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Simulation failed");
      } finally {
        setSimulating(false);
      }
    },
    [token, jobId, buildRequest],
  );

  // initial load: job + baseline simulation (empty payload = current state)
  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const [j, baseline] = await Promise.all([
          getJobDetail(jobId),
          simulateWhatIf(jobId, {}, token),
        ]);
        if (cancelled) return;
        setJob(j);
        setResult(baseline);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, jobId]);

  const changed =
    drops.size > 0 ||
    expLevel !== "keep" ||
    remote !== "keep" ||
    salMin !== "" ||
    salMax !== "";

  const requiredSkills = useMemo(
    () => (job?.skills ?? []).filter((s) => s.is_required),
    [job],
  );
  const niceToHave = useMemo(
    () => (job?.skills ?? []).filter((s) => !s.is_required),
    [job],
  );

  const toggleDrop = (name: string) => {
    setDrops((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const dropLever = (name: string) => {
    const next = new Set(drops);
    next.add(name);
    setDrops(next);
    void runSimulation(buildRequest(next));
  };

  const resetAll = () => {
    setDrops(new Set());
    setExpLevel("keep");
    setRemote("keep");
    setSalMin("");
    setSalMax("");
    void runSimulation({
      drop_required_skills: [],
      experience_level: null,
      is_remote: null,
      salary_min: null,
      salary_max: null,
    });
  };

  const applyChanges = async () => {
    if (!job || !token) return;
    const payload: JobUpdatePayload = {};
    if (drops.size > 0) {
      payload.skills = job.skills.map((s) => ({
        skill_name: s.skill_name,
        is_required: s.is_required && !drops.has(s.skill_name),
        importance_weight: s.importance_weight,
      }));
    }
    if (expLevel !== "keep") payload.experience_level = expLevel;
    if (remote !== "keep") payload.is_remote = remote === "remote";
    if (salMin !== "") payload.salary_min = Number(salMin);
    if (salMax !== "") payload.salary_max = Number(salMax);

    setApplying(true);
    try {
      await updateJob(job.id, payload, token);
      toast.success("Posting updated with the simulated relaxation.");
      const fresh = await getJobDetail(jobId);
      setJob(fresh);
      setDrops(new Set());
      setExpLevel("keep");
      setRemote("keep");
      setSalMin("");
      setSalMax("");
      setResult(await simulateWhatIf(jobId, {}, token));
      router.refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update posting");
    } finally {
      setApplying(false);
    }
  };

  if (authLoading || !ready) return <EmployerLoading />;

  const reachDelta = result ? result.reach_after - result.reach_before : 0;
  const fitDelta =
    result && result.avg_fit_before != null && result.avg_fit_after != null
      ? Math.round((result.avg_fit_after - result.avg_fit_before) * 10) / 10
      : null;
  const healthDelta = result
    ? Math.round((result.jd_health_after - result.jd_health_before) * 10) / 10
    : 0;

  const inputCls =
    "rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-teal-500 focus:outline-none";

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
          <Wand2 className="h-4 w-4" />
          What-If relaxer
        </div>
        <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-zinc-100 sm:text-3xl">
          {loading ? "Loading…" : result?.title ?? job?.title ?? "Posting"}
        </h1>
      </div>

      <div className="mt-4">
        <PostingTabs jobId={jobId} active="whatif" />
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
          <div className="mt-6 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="max-w-3xl">
              <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                <Sparkles className="h-4 w-4 text-teal-400" />
                Relax a constraint, see the effect — before you commit
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
                Market reach (aggregate profile counts), fit impact on your own applicants and JD
                health are all recomputed live under the simulated posting. Nothing changes until
                you press Apply.
              </p>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-950/70 px-3 py-2 text-[11px] font-medium text-zinc-400 ring-1 ring-inset ring-zinc-800">
              <CheckCircle2 className="h-3.5 w-3.5 text-teal-500" />
              Simulation only — the posting stays untouched
            </span>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-[380px_1fr]">
            {/* ---------- Controls ---------- */}
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
                  Relaxations
                </h2>
                {changed && (
                  <button
                    type="button"
                    onClick={resetAll}
                    className="inline-flex items-center gap-1 text-xs font-medium text-zinc-400 hover:text-zinc-200"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Reset
                  </button>
                )}
              </div>

              {/* required skills */}
              <div className="mt-4">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                  Required skills
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {requiredSkills.length === 0 && (
                    <span className="text-xs text-zinc-500">
                      None marked required — add some on the edit page.
                    </span>
                  )}
                  {requiredSkills.map((s) => {
                    const relaxed = drops.has(s.skill_name);
                    return (
                      <button
                        key={s.skill_name}
                        type="button"
                        onClick={() => toggleDrop(s.skill_name)}
                        title={
                          relaxed
                            ? "Currently simulated as relaxed — click to restore"
                            : "Click to relax this requirement"
                        }
                        className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors ${
                          relaxed
                            ? "bg-rose-500/10 text-rose-300 ring-rose-500/30 line-through"
                            : "bg-teal-500/10 text-teal-300 ring-teal-500/30 hover:bg-teal-500/20"
                        }`}
                      >
                        {s.skill_name}
                      </button>
                    );
                  })}
                </div>
                {niceToHave.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                      Nice-to-have
                    </span>
                    {niceToHave.map((s) => (
                      <span
                        key={s.skill_name}
                        className="rounded-full bg-zinc-800/70 px-2.5 py-0.5 text-[11px] text-zinc-500 ring-1 ring-inset ring-zinc-700/50"
                      >
                        {s.skill_name}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* experience + remote */}
              <div className="mt-4 grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Experience
                  </span>
                  <select
                    value={expLevel}
                    onChange={(e) =>
                      setExpLevel(e.target.value as ExperienceLevel | "keep")
                    }
                    className={`${inputCls} mt-1.5 w-full`}
                  >
                    <option value="keep">Keep ({job?.experience_level ?? "—"})</option>
                    {LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                    Work mode
                  </span>
                  <select
                    value={remote}
                    onChange={(e) => setRemote(e.target.value as RemoteChoice)}
                    className={`${inputCls} mt-1.5 w-full`}
                  >
                    <option value="keep">Keep ({job?.is_remote ? "remote" : "on-site"})</option>
                    <option value="remote">Remote</option>
                    <option value="onsite">On-site</option>
                  </select>
                </label>
              </div>

              {/* salary */}
              <div className="mt-4">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                  Salary band ({job?.salary_currency ?? "USD"})
                </span>
                <div className="mt-1.5 grid grid-cols-2 gap-3">
                  <input
                    type="number"
                    min={0}
                    value={salMin}
                    onChange={(e) => setSalMin(e.target.value)}
                    placeholder={`Keep (${job?.salary_min ?? "—"})`}
                    className={inputCls}
                  />
                  <input
                    type="number"
                    min={0}
                    value={salMax}
                    onChange={(e) => setSalMax(e.target.value)}
                    placeholder={`Keep (${job?.salary_max ?? "—"})`}
                    className={inputCls}
                  />
                </div>
              </div>

              {/* actions */}
              <div className="mt-5 space-y-2">
                <button
                  type="button"
                  onClick={() => void runSimulation()}
                  disabled={simulating}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Zap className="h-4 w-4" />
                  {simulating ? "Simulating…" : "Simulate"}
                </button>
                <button
                  type="button"
                  onClick={() => void applyChanges()}
                  disabled={!changed || applying}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900/60 px-4 py-2.5 text-sm font-semibold text-zinc-200 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Save className="h-4 w-4" />
                  {applying ? "Applying…" : "Apply to posting"}
                </button>
                {!changed && (
                  <p className="text-center text-[11px] text-zinc-600">
                    Make a change above to enable Apply.
                  </p>
                )}
              </div>
            </div>

            {/* ---------- Results ---------- */}
            <div className="space-y-6">
              {/* reach */}
              <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                    <Users className="h-4 w-4 text-teal-400" />
                    Market reach
                  </div>
                  <span className="text-[11px] text-zinc-500">
                    of {result?.total_seekers ?? 0} seeker profiles — aggregate counts only, the
                    pool stays private
                  </span>
                </div>

                <div className="mt-4 flex flex-wrap items-end gap-5">
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-zinc-600">
                      Current
                    </div>
                    <div className="text-3xl font-bold tabular-nums text-zinc-400">
                      {result?.reach_before ?? 0}
                    </div>
                  </div>
                  <ArrowRight className="mb-2.5 h-5 w-5 text-zinc-600" />
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-zinc-600">
                      Simulated
                    </div>
                    <div className="text-3xl font-bold tabular-nums text-zinc-100">
                      {result?.reach_after ?? 0}
                    </div>
                  </div>
                  {result && <div className="mb-1.5"><DeltaChip value={reachDelta} /></div>}
                  <div className="mb-1 text-xs text-zinc-500">
                    seeker profiles holding every remaining required skill
                  </div>
                </div>
              </div>

              {/* fit + health */}
              <div className="grid gap-6 sm:grid-cols-2">
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                    <Target className="h-4 w-4 text-teal-400" />
                    Avg fit — your applicants
                  </div>
                  {result && result.applicants_scored > 0 ? (
                    <>
                      <div className="mt-3 flex items-end gap-3">
                        <span className="text-2xl font-bold tabular-nums text-zinc-400">
                          {result.avg_fit_before?.toFixed(1)}
                        </span>
                        <ArrowRight className="mb-1.5 h-4 w-4 text-zinc-600" />
                        <span className="text-2xl font-bold tabular-nums text-zinc-100">
                          {result.avg_fit_after?.toFixed(1)}
                        </span>
                        {fitDelta != null && (
                          <span className="mb-1.5">
                            <DeltaChip value={fitDelta} />
                          </span>
                        )}
                      </div>
                      <div className="mt-1.5 text-[11px] text-zinc-500">
                        across {result.applicants_scored} scored applicant
                        {result.applicants_scored === 1 ? "" : "s"} — same eight-component
                        engine, assistive only
                      </div>
                    </>
                  ) : (
                    <p className="mt-3 text-xs text-zinc-500">
                      No applicants to re-score yet. Fit impact appears once people apply.
                    </p>
                  )}
                </div>

                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                    <Gauge className="h-4 w-4 text-teal-400" />
                    JD health
                  </div>
                  <div className="mt-3 flex items-end gap-3">
                    <span className="text-2xl font-bold tabular-nums text-zinc-400">
                      {result?.jd_health_before.toFixed(0)}%
                    </span>
                    <ArrowRight className="mb-1.5 h-4 w-4 text-zinc-600" />
                    <span className="text-2xl font-bold tabular-nums text-zinc-100">
                      {result?.jd_health_after.toFixed(0)}%
                    </span>
                    <span className="mb-1.5">
                      <DeltaChip value={healthDelta} unit=" pts" />
                    </span>
                  </div>
                  <div className="mt-1.5 text-[11px] text-zinc-500">
                    deterministic checklist — dropping your last required skill costs points
                  </div>
                </div>
              </div>

              {/* effects */}
              {result && (
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                    <Activity className="h-4 w-4 text-teal-400" />
                    What changes
                  </div>
                  <ul className="mt-3 space-y-2">
                    {result.effects.map((e, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-zinc-300">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-400" />
                        {e}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* biggest levers */}
              {result && result.drop_options.length > 0 && (
                <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                    <Zap className="h-4 w-4 text-teal-400" />
                    Biggest single-skill levers
                  </div>
                  <p className="mt-1.5 text-[11px] text-zinc-500">
                    Reach if you dropped each remaining required skill on its own. Click to add it
                    to the simulation.
                  </p>
                  <ul className="mt-3 space-y-1.5">
                    {result.drop_options.map((opt) => (
                      <li key={opt.skill}>
                        <button
                          type="button"
                          onClick={() => dropLever(opt.skill)}
                          disabled={simulating}
                          className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-4 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-zinc-800/50 disabled:opacity-50"
                        >
                          <span className="text-sm font-medium text-zinc-200">{opt.skill}</span>
                          <span className="text-xs tabular-nums text-zinc-500">
                            reach → {opt.reach_if_dropped.toLocaleString()}
                          </span>
                          <DeltaChip value={opt.gain} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
