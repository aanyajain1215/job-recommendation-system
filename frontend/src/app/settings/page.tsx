"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  clearAlertHistory,
  getAlertSettings,
  getPreferences,
  previewAlertMatches,
  resetPreferences,
  updateAlertSettings,
} from "@/lib/api";
import { AlertPreview, AlertSettings, PreferenceState } from "@/lib/types";
import { BellRing, History, Info, Mail, RotateCcw, Settings2, Sparkles } from "lucide-react";

export default function SettingsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [prefs, setPrefs] = useState<PreferenceState | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertSettings | null>(null);
  const [alertsSaving, setAlertsSaving] = useState(false);
  const [alertsNote, setAlertsNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<AlertPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      setPrefs(await getPreferences(token));
      try {
        setAlerts(await getAlertSettings(token));
      } catch {
        setAlerts(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load preferences");
    } finally {
      setLoading(false);
    }
  }, [token]);

  const saveAlerts = async () => {
    if (!token || !alerts) return;
    setAlertsSaving(true);
    setAlertsNote(null);
    try {
      const saved = await updateAlertSettings(
        {
          enabled: alerts.enabled,
          email_enabled: alerts.email_enabled,
          digest_frequency: alerts.digest_frequency as "daily" | "weekly" | "off",
          min_score: alerts.min_score,
          max_items: alerts.max_items,
        },
        token,
      );
      setAlerts(saved);
      setAlertsNote("Saved");
      setPreview(null);
    } catch (err) {
      setAlertsNote(err instanceof Error ? err.message : "Failed to save alert settings");
    } finally {
      setAlertsSaving(false);
    }
  };

  const runPreview = async () => {
    if (!token || !alerts) return;
    setPreviewing(true);
    setAlertsNote(null);
    try {
      setPreview(await previewAlertMatches(token, { minScore: alerts.min_score }));
    } catch (err) {
      setAlertsNote(err instanceof Error ? err.message : "Failed to preview matches");
    } finally {
      setPreviewing(false);
    }
  };

  const clearHistory = async () => {
    if (!token) return;
    if (!confirm("Forget already-alerted jobs? Future runs may alert them again.")) return;
    try {
      await clearAlertHistory(token);
      setAlertsNote("Alert history cleared");
      setPreview(null);
    } catch (err) {
      setAlertsNote(err instanceof Error ? err.message : "Failed to clear history");
    }
  };

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (token && user) load();
  }, [user, token, authLoading, router, load]);

  const handleReset = async () => {
    if (!token) return;
    if (!confirm("Reset learned weights and skill affinities back to defaults?")) return;
    setResetting(true);
    try {
      setPrefs(await resetPreferences(token));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to reset preferences");
    } finally {
      setResetting(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  const maxWeight = Math.max(0.001, ...(prefs?.weights.map((w) => Math.max(w.weight, w.global_weight)) ?? [0.001]));

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 border-b border-zinc-800/80 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
            <Settings2 className="h-4 w-4" />
            Your preferences
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">Personalization Settings</h1>
          <p className="mt-1 text-sm text-zinc-400">
            The model adapts the 8 scoring weights from your feedback — bounded, shrunk toward
            defaults, and fully resettable (plan §16). Scores stay deterministic; only weights move.
          </p>
        </div>
        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          className="inline-flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50"
        >
          <RotateCcw className={`h-4 w-4 ${resetting ? "animate-spin" : ""}`} />
          Reset to defaults
        </button>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      {prefs && (
        <>
          {/* Meta + note */}
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Feedback events
              </p>
              <p className="mt-1.5 text-2xl font-bold text-zinc-100">{prefs.n_events}</p>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Shrinkage toward defaults
              </p>
              <p className="mt-1.5 text-2xl font-bold text-zinc-100">
                {(prefs.shrinkage * 100).toFixed(0)}%
              </p>
              <p className="mt-1 text-[11px] text-zinc-500">n / (n + 10), empirical-Bayes</p>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Skill leans
              </p>
              <p className="mt-1.5 text-2xl font-bold text-zinc-100">{prefs.affinities.length}</p>
            </div>
          </div>

          {prefs.personalization_note && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-teal-500/20 bg-teal-500/5 p-4 text-xs text-teal-300/90">
              <Info className="mt-px h-4 w-4 flex-shrink-0 text-teal-400" />
              {prefs.personalization_note}
            </div>
          )}

          {/* Weight bars */}
          <div className="mt-8 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <Sparkles className="h-4 w-4 text-teal-400" />
                Learned scoring weights
              </h2>
              <span className="text-[11px] text-zinc-500">▮ current · │ global default</span>
            </div>
            <div className="mt-5 space-y-4">
              {prefs.weights.map((w) => (
                <div key={w.component}>
                  <div className="mb-1.5 flex items-center justify-between text-xs">
                    <span className="font-medium text-zinc-300">{w.label}</span>
                    <span className="font-mono text-zinc-400">
                      {w.weight.toFixed(3)}
                      {Math.abs(w.weight - w.global_weight) >= 0.004 && (
                        <span className={w.weight > w.global_weight ? "ml-1.5 text-emerald-400" : "ml-1.5 text-amber-400"}>
                          {w.weight > w.global_weight ? "▲" : "▼"} {w.global_weight.toFixed(3)}
                        </span>
                      )}
                    </span>
                  </div>
                  <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
                    <div
                      className={`h-full rounded-full transition-all ${
                        w.weight >= w.global_weight ? "bg-teal-400" : "bg-amber-400"
                      }`}
                      style={{ width: `${(w.weight / maxWeight) * 100}%` }}
                    />
                    <div
                      className="absolute inset-y-0 w-0.5 bg-zinc-500"
                      style={{ left: `${(w.global_weight / maxWeight) * 100}%` }}
                      title={`Global default ${w.global_weight}`}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <BellRing className="h-4 w-4 text-teal-400" />
                Job alerts from your saved jobs
              </h2>
              <Link href="/notifications" className="text-xs font-medium text-teal-400 hover:text-teal-300">
                View notifications →
              </Link>
            </div>
            {alerts === null ? (
              <p className="mt-4 text-xs text-zinc-500">
                Alerts need a profile. Complete your profile, save a few jobs, then come back.
              </p>
            ) : (
              <>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                  We compare newly posted jobs with the jobs you saved and notify you when similar roles go live.
                  In-app alerts are always available; email is optional.
                </p>
                <div className="mt-5 grid grid-cols-1 gap-5 sm:grid-cols-2">
                  <label className="flex items-start gap-3 rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-3">
                    <input
                      type="checkbox"
                      checked={alerts.enabled}
                      onChange={(e) => setAlerts({ ...alerts, enabled: e.target.checked })}
                      className="mt-0.5 h-4 w-4 accent-teal-500"
                    />
                    <span>
                      <span className="block text-xs font-semibold text-zinc-200">Enable job alerts</span>
                      <span className="block text-[11px] text-zinc-500">Pause anytime without losing history.</span>
                    </span>
                  </label>
                  <label className="flex items-start gap-3 rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-3">
                    <input
                      type="checkbox"
                      checked={alerts.email_enabled}
                      onChange={(e) => setAlerts({ ...alerts, email_enabled: e.target.checked })}
                      className="mt-0.5 h-4 w-4 accent-teal-500"
                    />
                    <span>
                      <span className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
                        <Mail className="h-3.5 w-3.5 text-zinc-400" /> Email me a digest
                      </span>
                      <span className="block text-[11px] text-zinc-500">Requires SMTP configuration.</span>
                    </span>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-zinc-400">Frequency</span>
                    <select
                      value={alerts.digest_frequency}
                      onChange={(e) => setAlerts({ ...alerts, digest_frequency: e.target.value })}
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-200"
                    >
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                      <option value="off">Off</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-zinc-400">Max jobs per digest</span>
                    <select
                      value={alerts.max_items}
                      onChange={(e) => setAlerts({ ...alerts, max_items: Number(e.target.value) })}
                      className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-200"
                    >
                      {[3, 5, 8, 10, 15].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="mb-1.5 flex items-center justify-between text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                      <span>Minimum match score</span>
                      <span className="font-mono text-teal-300">{alerts.min_score.toFixed(0)}</span>
                    </span>
                    <input
                      type="range"
                      min={30}
                      max={90}
                      step={5}
                      value={alerts.min_score}
                      onChange={(e) => setAlerts({ ...alerts, min_score: Number(e.target.value) })}
                      className="w-full accent-teal-500"
                    />
                  </label>
                </div>
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <button type="button" onClick={saveAlerts} disabled={alertsSaving} className="rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 disabled:opacity-50">
                    {alertsSaving ? "Saving…" : "Save alert settings"}
                  </button>
                  <button type="button" onClick={runPreview} disabled={previewing} className="rounded-lg border border-zinc-700 px-4 py-2 text-xs font-medium text-zinc-200 disabled:opacity-50">
                    {previewing ? "Scanning…" : "Preview matches"}
                  </button>
                  <button type="button" onClick={clearHistory} className="ml-auto text-[11px] font-medium text-zinc-500 hover:text-rose-400">
                    Clear alert history
                  </button>
                  {alertsNote && <span className="w-full text-[11px] text-teal-300/90">{alertsNote}</span>}
                </div>
                {preview && (
                  <div className="mt-4 rounded-xl border border-zinc-800/70 bg-zinc-950/40 p-4">
                    <p className="text-[11px] text-zinc-400">
                      {preview.items.length === 0
                        ? "No new matches right now — nothing to alert."
                        : `${preview.items.length} match${preview.items.length === 1 ? "" : "es"} from ${preview.seeds_used} saved job${preview.seeds_used === 1 ? "" : "s"}.`}
                    </p>
                    {preview.items.length > 0 && (
                      <ul className="mt-3 space-y-2">
                        {preview.items.map((match) => (
                          <li key={match.job.id} className="flex items-start justify-between gap-3">
                            <Link href={`/jobs/${match.job.id}`} className="min-w-0 flex-1 text-xs text-zinc-200 hover:text-teal-300">
                              <span className="font-semibold">{match.job.title}</span>
                              {match.job.company_name && <span className="text-zinc-500"> · {match.job.company_name}</span>}
                              <span className="mt-0.5 block truncate text-[11px] text-zinc-500">{match.reason}</span>
                            </Link>
                            <span className="font-mono text-[10px] text-teal-300">{match.score.toFixed(0)}%</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Recent learned changes */}
          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <History className="h-4 w-4 text-teal-400" />
                Recent learned changes
              </h2>
              {prefs.history.length === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  No weight movement yet — give feedback on a recommendation to start learning.
                </p>
              ) : (
                <ul className="mt-4 space-y-2.5">
                  {[...prefs.history].reverse().map((h, i) => (
                    <li key={i} className="flex items-center justify-between text-xs">
                      <span className="capitalize text-zinc-300">
                        {h.component}{" "}
                        <span className="text-zinc-500">· {h.reason.replace(/_/g, " ")}</span>
                      </span>
                      <span className="font-mono">
                        <span className={h.delta >= 0 ? "text-emerald-400" : "text-amber-400"}>
                          {h.delta >= 0 ? "+" : ""}
                          {h.delta.toFixed(4)}
                        </span>{" "}
                        <span className="text-zinc-500">→ {h.weight.toFixed(3)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Skill affinities */}
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">
                <Sparkles className="h-4 w-4 text-teal-400" />
                Skill leans (30-day half-life)
              </h2>
              {prefs.affinities.length === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  No skill leans yet — feedback like &quot;too difficult&quot; or &quot;relevant&quot;
                  leans the skills a job requires. Leans never hide a skill completely.
                </p>
              ) : (
                <div className="mt-4 flex flex-wrap gap-2">
                  {prefs.affinities.map((a) => (
                    <span
                      key={a.skill}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                        a.score >= 0
                          ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                          : "bg-rose-500/10 text-rose-300 ring-rose-500/30"
                      }`}
                      title={`Affinity ${a.score.toFixed(3)} — credit scaled by max(0, 1 + affinity·0.3)`}
                    >
                      {a.skill}
                      <span className="font-mono text-[10px] opacity-80">
                        {a.score >= 0 ? "+" : ""}
                        {a.score.toFixed(2)}
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="mt-6 rounded-xl border border-zinc-800/60 bg-zinc-950/40 p-4 text-[11px] leading-relaxed text-zinc-500">
            How it works: each feedback event applies one bounded multiplicative step (η=0.15)
            toward or away from that job&apos;s component profile, clamped to [0.5×, 2.0×] of the
            global weights and renormalized to Σ=1. With few events, weights shrink toward the
            defaults (n/(n+10)) so new users aren&apos;t over-fit. The LLM never assigns scores.
          </div>

          <div className="mt-6 flex justify-center">
            <Link
              href="/recommendations"
              className="text-xs font-semibold text-teal-400 hover:text-teal-300"
            >
              Back to recommendations
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
