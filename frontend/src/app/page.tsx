import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Compass,
  ListChecks,
  Sparkles,
  Target,
} from "lucide-react";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      {/* Hero Section */}
      <section className="relative overflow-hidden border-b border-zinc-800/80 bg-gradient-to-b from-zinc-900/40 via-zinc-950 to-zinc-950 px-4 py-20 sm:px-6 lg:px-8">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(45rem_50rem_at_top,rgba(255,219,187,0.5),transparent)]" />

        <div className="mx-auto max-w-4xl text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-teal-500/30 bg-teal-500/10 px-3.5 py-1 text-xs font-semibold text-teal-300 backdrop-blur">
            <Sparkles className="h-3.5 w-3.5" />
            AI-Powered Job Matching
          </div>

          <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-zinc-100 sm:text-6xl">
            Find roles that genuinely{" "}
            <span className="bg-gradient-to-r from-teal-400 via-teal-200 to-cyan-400 bg-clip-text text-transparent">
              fit your skills
            </span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-base sm:text-lg leading-relaxed text-zinc-400">
            Upload your resume or list your skills to get personalized AI job recommendations,
            clear skill-gap breakdowns, and an organized saved jobs list.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3.5">
            <Link
              href="/register"
              className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-5 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all"
            >
              Get Started Free
              <ArrowRight className="h-4 w-4" />
            </Link>

            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/70 px-5 py-3 text-sm font-medium text-zinc-200 hover:bg-zinc-800 hover:text-zinc-100 transition-colors"
            >
              Sign In
            </Link>
          </div>
        </div>

        {/* Feature Cards Grid */}
        <div className="mx-auto mt-16 max-w-6xl grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10 text-teal-400 ring-1 ring-teal-500/30">
              <Sparkles className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              AI Skill Matching
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Matches your skills, experience, and career goals against open roles so you see relevant opportunities first.
            </p>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 ring-1 ring-indigo-500/30">
              <Target className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              Clear Skill-Gap Breakdown
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              See which skills you already bring, what is missing, and a step-by-step learning plan to close the gap.
            </p>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-600 ring-1 ring-cyan-500/30">
              <Compass className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              Learns What You Prefer
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Saving roles, applying, and rating recommendations helps refine future matches to fit your preferences.
            </p>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="px-4 py-14 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl">
          <div className="text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-teal-400">
              How It Works
            </p>
            <h2 className="mt-1 text-2xl font-bold text-zinc-100">
              From resume to offer in three steps
            </h2>
          </div>

          <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-3">
            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <div className="flex items-center gap-2 text-sm font-semibold text-teal-400">
                <CheckCircle2 className="h-4 w-4" />
                1. Build your profile
              </div>
              <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                Upload your resume to auto-fill your experience and skills, or add them manually in minutes.
              </p>
            </div>

            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <div className="flex items-center gap-2 text-sm font-semibold text-teal-400">
                <Sparkles className="h-4 w-4" />
                2. Review AI matches
              </div>
              <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                Browse roles ranked by fit, inspect skill-gap explanations, and preview What-If career scenarios.
              </p>
            </div>

            <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
              <div className="flex items-center gap-2 text-sm font-semibold text-teal-400">
                <ListChecks className="h-4 w-4" />
                3. Track every application
              </div>
              <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                Save promising roles, apply directly, and follow each application stage from submission to offer.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
