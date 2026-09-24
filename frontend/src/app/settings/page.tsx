"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getPreferences, resetPreferences } from "@/lib/api";
import { PreferenceState } from "@/lib/types";
import { History, Info, RotateCcw, Settings2, Sparkles } from "lucide-react";

export default function SettingsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [prefs, setPrefs] = useState<PreferenceState | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      setPrefs(await getPreferences(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load preferences");
    } finally {
      setLoading(false);
    }
  }, [token]);

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
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">Personalization Settings</h1>
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
              <p className="mt-1.5 text-2xl font-bold text-white">{prefs.n_events}</p>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Shrinkage toward defaults
              </p>
              <p className="mt-1.5 text-2xl font-bold text-white">
                {(prefs.shrinkage * 100).toFixed(0)}%
              </p>
              <p className="mt-1 text-[11px] text-zinc-500">n / (n + 10), empirical-Bayes</p>
            </div>
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                Skill leans
              </p>
              <p className="mt-1.5 text-2xl font-bold text-white">{prefs.affinities.length}</p>
            </div>
          </div>

          {prefs.personalization_note && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-teal-500/20 bg-teal-500/5 p-4 text-xs text-teal-200/90">
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
