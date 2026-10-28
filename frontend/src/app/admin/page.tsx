"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  getAdminConfig,
  getAdminModels,
  getAdminSkills,
  getJobDuplicates,
  getLlmUsage,
  getParseFailures,
  mergeSkills,
  putAdminConfig,
  retryParse,
} from "@/lib/api";
import {
  AdminConfigResponse,
  AdminSkillsResponse,
  DuplicatesResponse,
  LlmUsageResponse,
  MergeReport,
  ModelRegistryItem,
  ParseFailuresResponse,
} from "@/lib/types";
import {
  AlertTriangle,
  Copy,
  GitMerge,
  Loader2,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wrench,
} from "lucide-react";

export default function AdminPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // skill merge
  const [skillQuery, setSkillQuery] = useState("");
  const [skills, setSkills] = useState<AdminSkillsResponse | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [mergeBusy, setMergeBusy] = useState(false);
  const [mergeReport, setMergeReport] = useState<MergeReport | null>(null);

  // ops panels
  const [duplicates, setDuplicates] = useState<DuplicatesResponse | null>(null);
  const [usage, setUsage] = useState<LlmUsageResponse | null>(null);
  const [failures, setFailures] = useState<ParseFailuresResponse | null>(null);
  const [models, setModels] = useState<ModelRegistryItem[]>([]);
  const [config, setConfig] = useState<AdminConfigResponse | null>(null);
  const [editWeights, setEditWeights] = useState<Record<string, number>>({});
  const [configBusy, setConfigBusy] = useState(false);
  const [configMsg, setConfigMsg] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      const [cfg, usageRes, failuresRes, modelsRes] = await Promise.all([
        getAdminConfig(token),
        getLlmUsage(token),
        getParseFailures(token),
        getAdminModels(token),
      ]);
      setConfig(cfg);
      setEditWeights(
        Object.fromEntries(cfg.weights.map((w) => [w.component, w.weight])),
      );
      setUsage(usageRes);
      setFailures(failuresRes);
      setModels(modelsRes.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (user && user.role !== "admin") {
      router.push("/dashboard");
      return;
    }
    if (token && user?.role === "admin") loadAll();
  }, [user, token, authLoading, router, loadAll]);

  const searchSkills = async (q?: string) => {
    if (!token) return;
    try {
      setSkills(await getAdminSkills(token, q));
    } catch {
      setSkills(null);
    }
  };

  const handleMerge = async () => {
    if (!token || !sourceId || !targetId) return;
    setMergeBusy(true);
    setError(null);
    try {
      const report = await mergeSkills(sourceId, targetId, token);
      setMergeReport(report);
      setSourceId("");
      setTargetId("");
      await searchSkills(skillQuery || undefined);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setMergeBusy(false);
    }
  };

  const loadDuplicates = async () => {
    if (!token) return;
    try {
      setDuplicates(await getJobDuplicates(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate scan failed");
    }
  };

  const handleRetry = async (resumeId: string) => {
    if (!token) return;
    setRetryingId(resumeId);
    try {
      await retryParse(resumeId, token);
      setFailures(await getParseFailures(token));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetryingId(null);
    }
  };

  const weightSum = Object.values(editWeights).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
  const sumValid = Math.abs(weightSum - 1) < 0.0005;

  const handleSaveConfig = async () => {
    if (!token) return;
    setConfigBusy(true);
    setConfigMsg(null);
    try {
      const saved = await putAdminConfig(editWeights, token);
      setConfigMsg(`Saved — Σw = ${saved.sum}`);
      await loadAll();
    } catch (err) {
      setConfigMsg(err instanceof Error ? err.message : "Save failed");
    } finally {
      setConfigBusy(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-rose-500 border-t-transparent" />
      </div>
    );
  }

  if (!user || user.role !== "admin") return null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="border-b border-zinc-800/80 pb-6">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-rose-400">
          <ShieldCheck className="h-4 w-4" />
          Admin Console · plan §22
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
          Operations & Data Integrity
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Skill merges run in one transaction; JSONB recommendation snapshots stay immutable.
          Weights validate Σ=1 on save; the LLM kill switch degrades every route to
          deterministic fallbacks.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      {/* Top row: LLM usage + config */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* LLM usage / cost meter */}
        <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <Sparkles className="h-4 w-4 text-teal-400" />
              LLM Usage & Cost Meter
            </h2>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
                usage?.llm_enabled
                  ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                  : "bg-amber-500/10 text-amber-300 ring-amber-500/30"
              }`}
            >
              {usage?.llm_enabled ? "LLM enabled" : "KILL SWITCH ACTIVE"}
            </span>
          </div>

          {usage && (
            <>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "Calls", value: usage.totals.calls },
                  { label: "Prompt tok", value: usage.totals.prompt_tokens },
                  { label: "Completion tok", value: usage.totals.completion_tokens },
                  {
                    label: "Est. cost",
                    value:
                      usage.totals.estimated_cost_usd === null
                        ? "n/a"
                        : `$${usage.totals.estimated_cost_usd.toFixed(4)}`,
                  },
                ].map((tile) => (
                  <div key={tile.label} className="rounded-lg bg-zinc-950/60 p-3">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                      {tile.label}
                    </p>
                    <p className="mt-1 text-sm font-bold text-zinc-100">{tile.value}</p>
                  </div>
                ))}
              </div>

              <div className="mt-4 flex items-center gap-2 text-[11px] text-zinc-500">
                <Terminal className="h-3.5 w-3.5" />
                Kill switch: <code className="text-amber-300">{config?.llm.kill_switch}</code>
                · provider {config?.llm.provider} / {config?.llm.model} · key{" "}
                {config?.llm.has_api_key ? "present" : "absent (fallbacks active)"}
              </div>

              {usage.by_route.length > 0 ? (
                <table className="mt-4 w-full text-left text-xs">
                  <thead>
                    <tr className="text-zinc-500">
                      <th className="pb-2 font-medium">Route</th>
                      <th className="pb-2 font-medium">Calls</th>
                      <th className="pb-2 font-medium">Tokens</th>
                      <th className="pb-2 font-medium">Avg ms</th>
                      <th className="pb-2 font-medium">Flagged</th>
                    </tr>
                  </thead>
                  <tbody className="text-zinc-300">
                    {usage.by_route.map((r) => (
                      <tr key={r.route} className="border-t border-zinc-800/60">
                        <td className="py-1.5 font-mono text-[11px]">{r.route}</td>
                        <td>{r.calls}</td>
                        <td>{r.prompt_tokens + r.completion_tokens}</td>
                        <td>{Math.round(r.avg_latency_ms)}</td>
                        <td className={r.flagged ? "text-amber-400" : ""}>{r.flagged}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="mt-4 text-xs text-zinc-500">
                  No LLM calls yet — every route is on its deterministic fallback.
                </p>
              )}
            </>
          )}
        </section>

        {/* Config weights */}
        <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <Wrench className="h-4 w-4 text-teal-400" />
              Scoring Weights
            </h2>
            <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-[11px] font-semibold text-zinc-300">
              source: {config?.source}
            </span>
          </div>

          {config && (
            <>
              <div className="mt-4 space-y-2.5">
                {config.weights.map((w) => (
                  <div key={w.component} className="flex items-center justify-between gap-3">
                    <span className="text-xs text-zinc-300">{w.label}</span>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        step={0.01}
                        min={0}
                        value={editWeights[w.component] ?? 0}
                        onChange={(e) =>
                          setEditWeights((prev) => ({
                            ...prev,
                            [w.component]: parseFloat(e.target.value),
                          }))
                        }
                        className="w-20 rounded-lg border border-zinc-800 bg-zinc-950/70 px-2 py-1 text-right font-mono text-xs text-zinc-200 focus:border-teal-500 focus:outline-none"
                        aria-label={`${w.label} weight`}
                      />
                      <span className="w-10 text-right text-[10px] text-zinc-600">
                        def {w.default}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-4 flex items-center justify-between">
                <span
                  className={`text-xs font-semibold ${sumValid ? "text-emerald-400" : "text-rose-400"}`}
                >
                  Σw = {weightSum.toFixed(4)} {sumValid ? "✓" : "— must equal 1.0000"}
                </span>
                <button
                  type="button"
                  onClick={handleSaveConfig}
                  disabled={!sumValid || configBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500 px-4 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
                >
                  {configBusy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  Save weights
                </button>
              </div>
              {configMsg && <p className="mt-2 text-xs text-teal-400">{configMsg}</p>}
              <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
                M4 bounds track this baseline: each feedback step stays within{" "}
                [{config.m4.bounds[0]}×, {config.m4.bounds[1]}×] with η={config.m4.learning_rate}{" "}
                and shrinkage n/(n+{config.m4.shrinkage_k}).
              </p>
            </>
          )}
        </section>
      </div>

      {/* Skill merge */}
      <section className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
          <GitMerge className="h-4 w-4 text-teal-400" />
          Skill Merge (transactional)
        </h2>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <input
              value={skillQuery}
              onChange={(e) => setSkillQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && searchSkills(skillQuery)}
              placeholder="Search skills (e.g. Node, React)…"
              className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
            />
          </div>
          <button
            type="button"
            onClick={() => searchSkills(skillQuery || undefined)}
            className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
          >
            Search
          </button>
        </div>

        {skills && (
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block text-xs text-zinc-400">
              Source (absorbed & removed)
              <select
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
              >
                <option value="">— pick source skill —</option>
                {skills.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.profiles} profiles / {s.jobs} jobs
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-zinc-400">
              Target (canonical survivor)
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
              >
                <option value="">— pick target skill —</option>
                {skills.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.profiles} profiles / {s.jobs} jobs
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <div className="mt-4 flex items-center justify-between">
          <p className="text-[11px] text-zinc-500">
            {skills ? `${skills.total_skills} skills total` : "Search to load skills"} ·
            profiles, jobs, aliases, edges & affinities re-pointed in one transaction
          </p>
          <button
            type="button"
            onClick={handleMerge}
            disabled={!sourceId || !targetId || sourceId === targetId || mergeBusy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
          >
            {mergeBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitMerge className="h-3.5 w-3.5" />}
            Merge into target
          </button>
        </div>

        {mergeReport && (
          <div className="mt-4 rounded-xl border border-teal-500/25 bg-teal-500/5 p-4 text-xs text-teal-300">
            <p className="font-semibold text-teal-300">
              Merged “{mergeReport.source.name}” → “{mergeReport.target.name}” · embedding{" "}
              {mergeReport.embedding_refreshed ? "refreshed" : "kept"}
            </p>
            <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-[11px] sm:grid-cols-5">
              <span>profiles +{mergeReport.profile_skills.moved} / −{mergeReport.profile_skills.deduped}</span>
              <span>jobs +{mergeReport.job_skills.moved} / −{mergeReport.job_skills.deduped}</span>
              <span>aliases +{mergeReport.skill_aliases.moved}</span>
              <span>edges +{mergeReport.skill_edges.moved}</span>
              <span>affinities +{mergeReport.skill_affinities.moved}</span>
            </div>
          </div>
        )}
      </section>

      {/* Duplicates + parse failures */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
              <Copy className="h-4 w-4 text-teal-400" />
              Duplicate Jobs
            </h2>
            <button
              type="button"
              onClick={loadDuplicates}
              className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Scan
            </button>
          </div>
          {!duplicates ? (
            <p className="mt-4 text-xs text-zinc-500">
              Cosine ≥ 0.92 + title similarity ≥ 0.60 — detection only; merging is a human
              decision (§24 cut line).
            </p>
          ) : duplicates.pairs.length === 0 ? (
            <p className="mt-4 text-xs text-zinc-500">
              No candidate pairs among {duplicates.jobs_examined} embedded jobs.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {duplicates.pairs.map((pair) => (
                <div
                  key={`${pair.job_a.id}-${pair.job_b.id}`}
                  className="rounded-lg border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-zinc-200">
                      {pair.job_a.title} ↔ {pair.job_b.title}
                    </span>
                    <span className="font-mono text-amber-300">
                      cos {pair.cosine} · title {pair.title_similarity}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-zinc-500">
                    keep → {pair.suggested_survivor_id.slice(0, 8)} · retire →{" "}
                    {pair.suggested_retire_id.slice(0, 8)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            Parse Failures
          </h2>
          {!failures || failures.items.length === 0 ? (
            <p className="mt-4 text-xs text-zinc-500">
              No failed or stuck resume parses. Stuck = “parsing” beyond{" "}
              {failures?.stuck_after_minutes ?? 15} minutes.
            </p>
          ) : (
            <ul className="mt-4 space-y-2">
              {failures.items.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800/70 bg-zinc-950/50 px-3 py-2 text-xs"
                >
                  <div className="min-w-0">
                    <p className="truncate text-zinc-200">
                      {item.original_filename || item.id.slice(0, 8)}{" "}
                      <span
                        className={
                          item.parse_status === "failed"
                            ? "text-rose-400"
                            : "text-amber-400"
                        }
                      >
                        ({item.parse_status}
                        {item.stuck ? ", stuck" : ""})
                      </span>
                    </p>
                    <p className="font-mono text-[10px] text-zinc-600">
                      profile {item.profile_id.slice(0, 8)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRetry(item.id)}
                    disabled={retryingId === item.id}
                    className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-50"
                  >
                    {retryingId === item.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3 w-3" />
                    )}
                    Retry
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Model registry */}
      <section className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
        <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
          <Terminal className="h-4 w-4 text-teal-400" />
          Model Registry
        </h2>
        {models.length === 0 ? (
          <p className="mt-4 text-xs text-zinc-500">
            No artifacts registered yet — run{" "}
            <code className="text-teal-300">python ml/train.py --all</code> to train and
            register M1–M3 (§21 gates).
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-zinc-500">
                  <th className="pb-2 font-medium">Model</th>
                  <th className="pb-2 font-medium">Version</th>
                  <th className="pb-2 font-medium">Active</th>
                  <th className="pb-2 font-medium">Artifact</th>
                  <th className="pb-2 font-medium">Trained</th>
                  <th className="pb-2 font-medium">Metrics</th>
                </tr>
              </thead>
              <tbody className="text-zinc-300">
                {models.map((m) => (
                  <tr key={m.id} className="border-t border-zinc-800/60">
                    <td className="py-2 font-semibold text-zinc-100">{m.name}</td>
                    <td className="font-mono">{m.version}</td>
                    <td>
                      {m.active ? (
                        <span className="text-emerald-400">● active</span>
                      ) : (
                        <span className="text-zinc-600">○ staged</span>
                      )}
                    </td>
                    <td className="font-mono text-[10px]">
                      {m.artifact_exists ? (
                        <span className="text-teal-400">on disk</span>
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                    <td className="text-[11px]">
                      {m.trained_at ? new Date(m.trained_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="max-w-[280px] truncate font-mono text-[10px] text-zinc-500">
                      {Object.entries(m.metrics)
                        .map(([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(4) : v}`)
                        .join(" · ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="mt-6 text-center">
        <Link href="/dashboard" className="text-xs font-semibold text-zinc-500 hover:text-zinc-300">
          ← Back to dashboard
        </Link>
      </div>
    </div>
  );
}
