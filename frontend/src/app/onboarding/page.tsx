"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  completeOnboarding,
  discoverCareers,
  getOnboardingFlow,
  nextOnboardingQuestion,
} from "@/lib/api";
import {
  OnboardingAnswer,
  OnboardingCompleteResponse,
  OnboardingFlowResponse,
  OnboardingQuestion,
} from "@/lib/types";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  SkipForward,
  Sparkles,
  Target,
} from "lucide-react";

type Side = "a" | "b" | "c";
type Step = "questions" | "family";

const OPTION_KEYS: Side[] = ["a", "b", "c"];

/** Options actually present on a question (legacy pairs only expose a/b). */
function optionsOf(q: OnboardingQuestion): Side[] {
  return OPTION_KEYS.filter((k) => q[k] !== undefined && q[k] !== null);
}

export default function OnboardingPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();

  const [flow, setFlow] = useState<OnboardingFlowResponse | null>(null);
  const [answers, setAnswers] = useState<OnboardingAnswer[]>([]);
  const [picking, setPicking] = useState<Side | null>(null);

  const [step, setStep] = useState<Step>("questions");
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
      getOnboardingFlow()
        .then(setFlow)
        .catch(() => setError("Failed to load onboarding questions."))
        .finally(() => setLoading(false));
    }
  }, [user, authLoading, router]);

  // Family presets (needs auth token).
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

  const minReached = flow ? answers.length >= flow.min_questions : false;
  const maxReached = flow ? answers.length >= flow.max_questions : false;
  const canFinish = minReached && !maxReached;

  const pick = useCallback(
    async (side: Side) => {
      if (!flow?.question || picking) return;
      const q = flow.question;
      const nextAnswers: OnboardingAnswer[] = [
        ...answers,
        { index: q.index, chosen: side },
      ];
      setPicking(side);
      setError(null);
      setAnswers(nextAnswers);
      try {
        const next = await nextOnboardingQuestion(nextAnswers);
        setFlow(next);
        // Bank exhausted or cap reached → move on to target family.
        if (!next.question || nextAnswers.length >= next.max_questions) {
          setStep("family");
        }
      } catch {
        // Roll back the optimistic answer so the user can retry.
        setAnswers(answers);
        setError("Couldn't fetch the next question — try again.");
      } finally {
        setPicking(null);
      }
    },
    [flow, answers, picking],
  );

  const goBack = useCallback(async () => {
    if (answers.length === 0 || picking) return;
    const trimmed = answers.slice(0, -1);
    setPicking("a");
    setError(null);
    try {
      const next = await nextOnboardingQuestion(trimmed);
      setAnswers(trimmed);
      setFlow(next);
      setStep("questions");
    } catch {
      setError("Couldn't go back — try again.");
    } finally {
      setPicking(null);
    }
  }, [answers, picking]);

  const handleComplete = async () => {
    if (!token || answers.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      setResult(
        await completeOnboarding(
          {
            answers,
            ...(family ? { target_family: family } : {}),
          },
          token,
        ),
      );
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

  const q = flow?.question ?? null;
  const preview = flow?.preview_weights ?? [];
  const previewMax = preview.length ? Math.max(...preview.map((w) => w.weight)) : 1;

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:px-8">
      <div className="border-b border-zinc-800/80 pb-6 text-center">
        <div className="inline-flex items-center gap-2 rounded-full bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30">
          <Sparkles className="h-3.5 w-3.5" />
          Adaptive setup · plan §6 M5
        </div>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-white">
          What do you look for in a job?
        </h1>
        <p className="mx-auto mt-2 max-w-2xl text-sm text-zinc-400">
          Answer a few quick picks — the next question adapts to your last answer, and your
          weights update live. You can skip anytime.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      {/* Progress */}
      <div className="mt-8 flex items-center gap-3">
        <div className="flex-1">
          <div className="mb-1 flex justify-between text-xs text-zinc-500">
            <span>
              {step === "family"
                ? "Almost done — pick a target family"
                : `Question ${answers.length + 1}`}
            </span>
            <span>
              {answers.length} answered · {flow?.min_questions ?? 3} to set weights
            </span>
          </div>
          <div className="h-2 rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-teal-400 transition-all"
              style={{
                width: `${
                  step === "family"
                    ? 100
                    : Math.min(
                        100,
                        (answers.length / (flow?.min_questions ?? 3)) * 100,
                      )
                }%`,
              }}
            />
          </div>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main card */}
        <div className="lg:col-span-2">
          {step === "family" ? (
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
              <p className="mt-3 text-xs text-zinc-500">
                This powers the career-interest match from your very first feed.
              </p>
            </div>
          ) : q ? (
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <p className="text-sm font-semibold text-zinc-300">
                <span className="mr-2 text-teal-400">Q{answers.length + 1}.</span>
                {q.question}
              </p>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                {optionsOf(q).map((side) => {
                  const option = q[side];
                  const selected =
                    answers[answers.length - 1]?.index === q.index &&
                    answers[answers.length - 1]?.chosen === side;
                  return (
                    <button
                      key={side}
                      type="button"
                      onClick={() => pick(side)}
                      disabled={picking !== null}
                      className={`rounded-xl border p-4 text-left transition-all disabled:opacity-60 ${
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

              <div className="mt-5 flex items-center justify-between">
                <button
                  type="button"
                  onClick={goBack}
                  disabled={answers.length === 0 || picking !== null}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-zinc-500 hover:text-zinc-300 disabled:opacity-40"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back
                </button>
                <div className="flex items-center gap-4">
                  {canFinish && (
                    <button
                      type="button"
                      onClick={() => setStep("family")}
                      disabled={picking !== null}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-400 hover:text-teal-300"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Good enough — finish
                    </button>
                  )}
                  {picking && (
                    <RefreshCw className="h-3.5 w-3.5 animate-spin text-zinc-500" />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6 text-center text-sm text-zinc-400">
              That&apos;s every question we have — pick a target family to finish.
            </div>
          )}
        </div>

        {/* Live weight preview */}
        <div className="lg:col-span-1">
          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Your weights (live)
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-zinc-600">
              Updates as you answer. Finalised when you finish.
            </p>
            <div className="mt-4 space-y-3">
              {preview.map((w) => (
                <div key={w.component}>
                  <div className="mb-1 flex justify-between text-[11px] text-zinc-400">
                    <span>{w.label}</span>
                    <span className="font-mono text-zinc-300">{w.weight.toFixed(3)}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-teal-400 transition-all"
                      style={{ width: `${(w.weight / previewMax) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Footer actions */}
      <div className="mt-8 flex flex-col items-center justify-between gap-4 sm:flex-row">
        <button
          type="button"
          onClick={() => router.push("/recommendations")}
          className="inline-flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-300"
        >
          <SkipForward className="h-3.5 w-3.5" />
          Skip — use default weights
        </button>
        {step === "family" && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setStep("questions")}
              className="inline-flex items-center gap-2 text-xs font-semibold text-zinc-500 hover:text-zinc-300"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to questions
            </button>
            <button
              type="button"
              onClick={handleComplete}
              disabled={answers.length === 0 || submitting}
              className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/20 hover:bg-teal-400 disabled:opacity-50"
            >
              {submitting ? "Fitting your weights…" : "Set my starting weights"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
