import Link from "next/link";
import { HealthPanel } from "@/components/health-panel";
import { fetchReadiness, getServerApiBaseUrl } from "@/lib/api";
import {
  ArrowRight,
  Briefcase,
  Compass,
  Cpu,
  Layers,
  Sparkles,
  Zap,
} from "lucide-react";

export const dynamic = "force-dynamic";

export default async function Home() {
  const initial = await fetchReadiness(getServerApiBaseUrl());

  return (
    <div className="flex flex-1 flex-col">
      {/* Hero Section */}
      <section className="relative overflow-hidden border-b border-zinc-800/80 bg-gradient-to-b from-zinc-900/40 via-zinc-950 to-zinc-950 px-4 py-20 sm:px-6 lg:px-8">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(45rem_50rem_at_top,rgba(255,219,187,0.5),transparent)]" />

        <div className="mx-auto max-w-4xl text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-teal-500/30 bg-teal-500/10 px-3.5 py-1 text-xs font-semibold text-teal-300 backdrop-blur">
            <Sparkles className="h-3.5 w-3.5" />
            Two-Stage Retrieve + Rank Recommendation Engine
          </div>

          <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-zinc-100 sm:text-6xl">
            Where talent meets opportunity{" "}
            <span className="bg-gradient-to-r from-teal-400 via-teal-200 to-cyan-400 bg-clip-text text-transparent">
              through real AI matching
            </span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-base sm:text-lg leading-relaxed text-zinc-400">
            A genuine recommendation system with semantic pgvector candidate retrieval,
            LightGBM re-ranking, and event-driven feedback loops. No mock data, no simple keyword filtering.
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
              Sign In to Your Feed
            </Link>
          </div>
        </div>

        {/* Feature Cards Grid */}
        <div className="mx-auto mt-16 max-w-6xl grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10 text-teal-400 ring-1 ring-teal-500/30">
              <Cpu className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              Semantic ANN Retrieval
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              pgvector powers 384-dimensional approximate nearest neighbor candidate generation from user profile embeddings.
            </p>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 ring-1 ring-indigo-500/30">
              <Layers className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              Two-Stage Re-Ranking
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Top candidate jobs are scored using LightGBM on skill overlap, seniority alignment, salary band fit, and recency.
            </p>
          </div>

          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 transition-colors">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30">
              <Zap className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-base font-semibold text-zinc-100">
              Active Feedback Loop
            </h3>
            <p className="mt-2 text-xs leading-relaxed text-zinc-400">
              Every view, bookmark, application, and dismiss event sharpens your profile embedding in near real-time.
            </p>
          </div>
        </div>
      </section>

      {/* Live System Diagnostics / Verification Panel */}
      <section className="px-4 py-12 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl">
          <div className="mb-4 text-center">
            <p className="text-xs font-semibold uppercase tracking-wider text-teal-400">
              Live Stack Telemetry
            </p>
            <p className="text-sm text-zinc-400">
              PostgreSQL 16 + pgvector + FastAPI + Next.js
            </p>
          </div>
          <HealthPanel initial={initial} />
        </div>
      </section>
    </div>
  );
}
