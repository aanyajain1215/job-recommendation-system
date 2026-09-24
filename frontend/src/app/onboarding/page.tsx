"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { completeOnboarding, discoverCareers, getOnboardingPairs } from "@/lib/api";
import { OnboardingCompleteResponse, OnboardingPairsResponse } from "@/lib/types";
import { ArrowRight, CheckCircle2, SkipForward, Sparkles, Target } from "lucide-react";

type Side = "a" | "b";

export default function OnboardingPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [data, setData] = useState<OnboardingPairsResponse | null>(null);
  const [choices, setChoices] = useState<Record<number, Side>>({});
  const [families, setFamilies] = useState<string[]>([]);
  const [family, setFamily] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<OnboardingCompleteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (user) {
      getOnboardingPairs()
        .then(setData)
        .catch(() => setError("Failed to load onboarding questions."))
        .finally(() => setLoading(false));
    }
  }, [user, authLoading, router]);

  // Separate lightweight fetch for family presets (needs auth token).
  useEffect(() => {
    if (!token || families.length > 0) return;
    discoverCareers(token)
      .then((resp) => {
        const names = [...resp.presets, ...resp.suggestions]
          .map((f) => f.family)
          .filter((v, i, arr) => arr.indexOf(v) === i);
        setFamilies(names);
      })
      .catch(() => setFamilies([]));
  }, [token, families.length]);

  const answered = data ? data.pairs.every((p) => choices[p.index] !== undefined) : false;

  const handleComplete = async () => {
    if (!token || !data || !answered) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        choices: data.pairs.map((p) => ({
          pair_index: p.index,
          chosen: choices[p.index],
        })),
        ...(family ? { target_family: family } : {}),
      };
      setResult(await completeOnboarding(payload, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your setup");
    } finally {
      setSubmitting(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  if (result) {
    const max = Math.max(...result.weights.map((w) => w.weight));
    return (
      <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6 lg:px-8">
        <div className="rounded-2xl border border-teal-500/25 bg-zinc-900/50 p-8 text-center">
          <CheckCircle2 className="mx-auto h-10 w-10 text-teal-400" />
          <h1 className="mt-4 text-2xl font-bold text-white">Your starting weights are set</h1>
          <p className="mt-2 text-sm text-zinc-400">{result.message}</p>
          {result.target_family && (
            <p className="mt-2 text-xs text-teal-300">
              Target family: {result.target_family}
            </p>
          )}

          <div className="mx-auto mt-6 max-w-md space-y-3 text-left">
            {result.weights.map((w) => (
              <div key={w.component}>
                <div className="mb-1 flex justify-between text-xs text-zinc-400">
                  <span>{w.label}</span>
                  <span className="font-mono text-zinc-300">{w.weight.toFixed(3)}</span>
                </div>
                <div className="h-2 rounded-full bg-zinc-800">
                  <div
                    className="h-full rounded-full bg-teal-400"
                    style={{ width: `${(w.weight / max) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="mt-7 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Link
              href="/recommendations"
              className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-teal-400"
            >
              See your matches <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/settings"
              className="text-xs font-semibold text-teal-400 hover:text-teal-300"
            >
              Review weights in Settings
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 lg:px-8">
      <div className="border-b border-zinc-800/80 pb-6 text-center">
        <div className="inline-flex items-center gap-2 rounded-full bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30">
          <Sparkles className="h-3.5 w-3.5" />
          Two-minute setup · plan §6 M5
        </div>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-white">
          What do you look for in a job?
        </h1>
        <p className="mx-auto mt-2 max-w-2xl text-sm text-zinc-400">
          {data?.note ??
            "Three quick picks set your starting weights (Bradley-Terry). Skip-able — defaults apply."}
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      <div className="mt-8 space-y-6">
        {data?.pairs.map((pair) => (
          <div
            key={pair.index}
            className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6"
          >
            <p className="text-sm font-semibold text-zinc-300">
              <span className="mr-2 text-teal-400">Q{pair.index + 1}.</span>
              {pair.question}
            </p>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(["a", "b"] as Side[]).map((side) => {
                const option = pair[side];
                const selected = choices[pair.index] === side;
                return (
                  <button
                    key={side}
                    type="button"
                    onClick={() =>
                      setChoices((prev) => ({ ...prev, [pair.index]: side }))
                    }
                    className={`rounded-xl border p-4 text-left transition-all ${
                      selected
                        ? "border-teal-500 bg-teal-500/10 shadow-lg shadow-teal-500/10"
                        : "border-zinc-800 bg-zinc-950/50 hover:border-zinc-700"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span
                        className={`text-sm font-semibold ${
                          selected ? "text-teal-300" : "text-zinc-200"
                        }`}
                      >
                        {option.label}
                      </span>
                      {selected && (
                        <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-teal-400" />
                      )}
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-zinc-500">
                      {option.blurb}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {/* Optional target family (§19 onboarding row) */}
        <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
          <label className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
            <Target className="h-4 w-4 text-teal-400" />
            Target career family (optional)
          </label>
          <select
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            className="mt-3 w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
          >
            <option value="">No preference yet — surprise me</option>
            {families.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-8 flex flex-col items-center justify-between gap-4 sm:flex-row">
        <button
          type="button"
          onClick={() => router.push("/recommendations")}
          className="inline-flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-300"
        >
          <SkipForward className="h-3.5 w-3.5" />
          Skip — use default weights
        </button>
        <button
          type="button"
          onClick={handleComplete}
          disabled={!answered || submitting}
          className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/20 hover:bg-teal-400 disabled:opacity-50"
        >
          {submitting ? "Fitting your weights…" : `Set my starting weights${answered ? "" : ` (${Object.keys(choices).length}/3)`}`}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
