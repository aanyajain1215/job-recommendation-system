"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getSimulations, runSimulation } from "@/lib/api";
import {
  History,
  Loader2,
  Play,
  Plus,
  Sparkles,
  Target,
  Wand2,
  X,
  Zap,
} from "lucide-react";
import { ResultDelta, SimulateRequest, SimulationListItem, SkillMutation } from "@/lib/types";
import { DeltaTable } from "@/components/delta-table";

const LEVELS = ["beginner", "intermediate", "advanced", "expert"] as const;
const WORK_MODES = ["remote", "hybrid", "onsite"] as const;

interface FormSkill {
  key: number;
  name: string;
  level: (typeof LEVELS)[number];
  years: string;
}

let formSkillCounter = 0;

export default function SimulatorPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();

  // Mutation form state (plan §10 schema)
  const [addSkills, setAddSkills] = useState<FormSkill[]>([]);
  const [removeSkills, setRemoveSkills] = useState<string[]>([]);
  const [removeText, setRemoveText] = useState("");
  const [salaryMin, setSalaryMin] = useState("");
  const [salaryMax, setSalaryMax] = useState("");
  const [location, setLocation] = useState("");
  const [workMode, setWorkMode] = useState<(typeof WORK_MODES)[number] | "">("");
  const [targetFamily, setTargetFamily] = useState("");
  const [projectName, setProjectName] = useState("");
  const [projectSkills, setProjectSkills] = useState("");
  const [certName, setCertName] = useState("");

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ResultDelta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SimulationListItem[]>([]);

  const fetchHistory = useCallback(async () => {
    if (!token) return;
    try {
      const data = await getSimulations(token, 5);
      setHistory(data.items);
    } catch {
      // History is non-critical; the run itself surfaces errors.
    }
  }, [token]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.push("/login");
      return;
    }
    fetchHistory();
  }, [user, authLoading, router, fetchHistory]);

  const addSkillRow = () =>
    setAddSkills((prev) => [
      ...prev,
      { key: ++formSkillCounter, name: "", level: "intermediate", years: "" },
    ]);

  const updateSkillRow = (key: number, patch: Partial<FormSkill>) =>
    setAddSkills((prev) => prev.map((s) => (s.key === key ? { ...s, ...patch } : s)));

  const removeSkillRow = (key: number) =>
    setAddSkills((prev) => prev.filter((s) => s.key !== key));

  const buildPayload = (): SimulateRequest | null => {
    const skills: SkillMutation[] = addSkills
      .filter((s) => s.name.trim())
      .map((s) => ({
        name: s.name.trim(),
        level: s.level,
        ...(s.years.trim() ? { years: Number(s.years) } : {}),
      }));

    const removals = [
      ...removeSkills,
      ...removeText
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    ];

    const payload: SimulateRequest = {};
    if (skills.length) payload.add_skills = skills;
    if (removals.length) payload.remove_skills = removals;
    if (salaryMin.trim() || salaryMax.trim()) {
      payload.expected_salary = {
        ...(salaryMin.trim() ? { min: Number(salaryMin) } : {}),
        ...(salaryMax.trim() ? { max: Number(salaryMax) } : {}),
        currency: "USD",
      };
    }
    if (location.trim()) payload.location = location.trim();
    if (workMode) payload.work_mode = workMode;
    if (targetFamily.trim()) payload.target_family = targetFamily.trim();
    if (projectName.trim() || projectSkills.trim()) {
      payload.add_project = {
        name: projectName.trim(),
        description: "",
        skills: projectSkills
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
    }
    if (certName.trim()) payload.add_cert = { name: certName.trim() };

    const isEmpty =
      !payload.add_skills &&
      !payload.remove_skills &&
      !payload.expected_salary &&
      !payload.location &&
      !payload.work_mode &&
      !payload.target_family &&
      !payload.add_project &&
      !payload.add_cert;
    if (isEmpty) return null;
    return payload;
  };

  const handleRun = async () => {
    if (!token) return;
    const payload = buildPayload();
    if (!payload) {
      setError("Add at least one change before running the simulation.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const data = await runSimulation(payload, token);
      setResult(data.result_delta);
      fetchHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const handleReset = () => {
    setAddSkills([]);
    setRemoveSkills([]);
    setRemoveText("");
    setSalaryMin("");
    setSalaryMax("");
    setLocation("");
    setWorkMode("");
    setTargetFamily("");
    setProjectName("");
    setProjectSkills("");
    setCertName("");
    setResult(null);
    setError(null);
  };

  if (authLoading) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-teal-400" />
      </div>
    );
  }

  const inputClass =
    "w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-teal-500/50 focus:outline-none focus:ring-1 focus:ring-teal-500/30";
  const labelClass = "block text-xs font-semibold text-zinc-400 mb-1.5";

  return (
    <div className="min-h-screen bg-zinc-950 pb-20 text-zinc-100">
      {/* Hero */}
      <div className="relative overflow-hidden border-b border-zinc-800 bg-gradient-to-b from-teal-950/30 via-zinc-950 to-zinc-950 py-10 px-4 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-6xl">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs font-bold text-teal-300 mb-3">
            <Wand2 className="h-3.5 w-3.5" /> What-If Simulator
          </span>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-zinc-100">
            Try a change before you make it
          </h1>
          <p className="mt-2 text-sm text-zinc-400 max-w-2xl">
            Add a skill, raise your salary expectation, or switch to remote — the
            simulator re-scores a shadow copy of your profile against live candidates.
            Your real profile is never modified.
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 mt-8 grid gap-8 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        {/* ---------------- Mutation form ---------------- */}
        <div className="space-y-5">
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                <Plus className="h-4 w-4 text-teal-400" /> Your mutation
              </h2>
              <button
                onClick={handleReset}
                className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                reset
              </button>
            </div>

            {/* Add skills */}
            <div className="mb-4">
              <span className={labelClass}>Add skills</span>
              <div className="space-y-2">
                {addSkills.map((row) => (
                  <div key={row.key} className="flex gap-1.5">
                    <input
                      value={row.name}
                      onChange={(e) => updateSkillRow(row.key, { name: e.target.value })}
                      placeholder="e.g. Docker"
                      className={inputClass}
                    />
                    <select
                      value={row.level}
                      onChange={(e) =>
                        updateSkillRow(row.key, { level: e.target.value as FormSkill["level"] })
                      }
                      className={`${inputClass} w-28`}
                    >
                      {LEVELS.map((l) => (
                        <option key={l} value={l}>
                          {l}
                        </option>
                      ))}
                    </select>
                    <input
                      value={row.years}
                      onChange={(e) => updateSkillRow(row.key, { years: e.target.value })}
                      placeholder="yrs"
                      type="number"
                      min={0}
                      max={50}
                      className={`${inputClass} w-16`}
                    />
                    <button
                      onClick={() => removeSkillRow(row.key)}
                      title="Remove"
                      className="flex-shrink-0 rounded-lg border border-zinc-800 px-2 text-zinc-500 hover:border-rose-500/40 hover:text-rose-400 transition-colors"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                <button
                  onClick={addSkillRow}
                  className="w-full rounded-lg border border-dashed border-zinc-700 py-2 text-xs font-semibold text-zinc-400 hover:border-teal-500/50 hover:text-teal-300 transition-colors"
                >
                  + Add a skill
                </button>
              </div>
            </div>

            {/* Remove skills */}
            <div className="mb-4">
              <label className={labelClass}>Remove skills (comma separated)</label>
              <input
                value={removeText}
                onChange={(e) => setRemoveText(e.target.value)}
                placeholder="e.g. PHP, jQuery"
                className={inputClass}
              />
            </div>

            {/* Salary */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              <div>
                <label className={labelClass}>Salary min</label>
                <input
                  value={salaryMin}
                  onChange={(e) => setSalaryMin(e.target.value)}
                  type="number"
                  min={0}
                  placeholder="90000"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Salary max</label>
                <input
                  value={salaryMax}
                  onChange={(e) => setSalaryMax(e.target.value)}
                  type="number"
                  min={0}
                  placeholder="130000"
                  className={inputClass}
                />
              </div>
            </div>

            {/* Location & mode */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              <div>
                <label className={labelClass}>Location</label>
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Berlin"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Work mode</label>
                <select
                  value={workMode}
                  onChange={(e) => setWorkMode(e.target.value as typeof workMode)}
                  className={inputClass}
                >
                  <option value="">any</option>
                  {WORK_MODES.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Target family */}
            <div className="mb-4">
              <label className={labelClass}>Target career family</label>
              <input
                value={targetFamily}
                onChange={(e) => setTargetFamily(e.target.value)}
                placeholder="e.g. DevOps Engineering"
                className={inputClass}
              />
            </div>

            {/* Project */}
            <div className="mb-4 grid grid-cols-2 gap-2">
              <div>
                <label className={labelClass}>New project</label>
                <input
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="K8s homelab"
                  className={inputClass}
                />
              </div>
              <div>
                <label className={labelClass}>Its skills</label>
                <input
                  value={projectSkills}
                  onChange={(e) => setProjectSkills(e.target.value)}
                  placeholder="Kubernetes, Docker"
                  className={inputClass}
                />
              </div>
            </div>

            {/* Certification */}
            <div className="mb-5">
              <label className={labelClass}>Certification</label>
              <input
                value={certName}
                onChange={(e) => setCertName(e.target.value)}
                placeholder="e.g. AWS Solutions Architect"
                className={inputClass}
              />
            </div>

            <button
              onClick={handleRun}
              disabled={running}
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-bold text-zinc-950 hover:bg-teal-400 disabled:opacity-60 disabled:cursor-not-allowed transition-all shadow-md shadow-teal-500/20"
            >
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Re-scoring candidates...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 fill-current" /> Run simulation
                </>
              )}
            </button>

            {error && (
              <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            )}
          </div>

          {/* Past runs */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-5">
            <h2 className="text-sm font-bold text-zinc-100 flex items-center gap-2 mb-3">
              <History className="h-4 w-4 text-zinc-500" /> Recent runs
            </h2>
            {history.length === 0 ? (
              <p className="text-xs text-zinc-600">No simulations yet.</p>
            ) : (
              <ul className="space-y-2">
                {history.map((item) => {
                  const delta =
                    item.result_delta.after.mean_score - item.result_delta.before.mean_score;
                  return (
                    <li
                      key={item.id}
                      className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2"
                    >
                      <span className="text-[11px] text-zinc-400">
                        {new Date(item.created_at).toLocaleString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {" · "}
                        {item.result_delta.deltas.length} candidates
                      </span>
                      <span
                        className={`text-xs font-bold ${delta > 0 ? "text-emerald-400" : delta < 0 ? "text-rose-400" : "text-zinc-500"}`}
                      >
                        {delta >= 0 ? "+" : ""}
                        {delta.toFixed(1)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* ---------------- Results ---------------- */}
        <div>
          {!result ? (
            <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-10 sm:p-14 text-center min-h-[400px] flex flex-col items-center justify-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-900 border border-zinc-800 mb-4">
                <Sparkles className="h-7 w-7 text-teal-400" />
              </div>
              <h3 className="text-lg font-semibold text-zinc-200">Counterfactuals appear here</h3>
              <p className="mt-2 text-sm text-zinc-500 max-w-md">
                Build a mutation on the left and run it — you&apos;ll see exactly how each
                candidate job&apos;s score and readiness band would shift, plus which
                skills move the needle most for your target role.
              </p>
              <Link
                href="/careers"
                className="mt-5 inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-2 text-xs font-semibold text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition-colors"
              >
                Explore alt careers <Target className="h-3.5 w-3.5" />
              </Link>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex items-center gap-2 text-sm font-bold text-zinc-100">
                <Zap className="h-4 w-4 text-teal-400 fill-current" />
                Simulation results
                <span className="ml-auto text-xs font-medium text-zinc-500">
                  profile unchanged — shadow re-score only
                </span>
              </div>
              <DeltaTable result={result} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
