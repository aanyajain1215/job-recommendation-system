"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getRecommendations, submitFeedback } from "@/lib/api";
import {
  FeedbackReason,
  RecommendationFeedResponse,
  RecommendationItem,
} from "@/lib/types";
import {
  AlertCircle,
  ArrowRight,
  Briefcase,
  CheckCircle2,
  ChevronRight,
  Compass,
  DollarSign,
  GraduationCap,
  Layers,
  MapPin,
  RefreshCw,
  Route,
  SlidersHorizontal,
  Sparkles,
  Target,
  ThumbsDown,
  TrendingUp,
  UserCheck,
  Wrench,
  Zap,
} from "lucide-react";

/** §16 feedback menu — every reason trains M4 (weights + skill affinities). */
const FEEDBACK_REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "relevant", label: "Relevant" },
  { value: "not_relevant", label: "Not relevant" },
  { value: "already_applied", label: "Already applied" },
  { value: "not_interested", label: "Not interested" },
  { value: "too_difficult", label: "Too difficult" },
  { value: "location_issue", label: "Location issue" },
  { value: "salary_issue", label: "Salary issue" },
  { value: "other", label: "Other" },
];

export default function RecommendationsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [feed, setFeed] = useState<RecommendationFeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [minMatchThreshold, setMinMatchThreshold] = useState<number>(0);
  const [refreshing, setRefreshing] = useState(false);
  const [feedbackMenu, setFeedbackMenu] = useState<string | null>(null);
  const [sendingFeedbackId, setSendingFeedbackId] = useState<string | null>(null);
  const [feedbackNotes, setFeedbackNotes] = useState<Record<string, string>>({});

  const fetchFeed = async () => {
    if (!token) return;
    try {
      setError(null);
      const data = await getRecommendations(token, 30);
      setFeed(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load recommendations");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (!authLoading) {
      if (!user) {
        router.push("/login");
      } else {
        fetchFeed();
      }
    }
  }, [user, token, authLoading]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchFeed();
  };

  const handleFeedback = async (jobId: string, reason: FeedbackReason) => {
    if (!token) return;
    setSendingFeedbackId(jobId);
    try {
      const resp = await submitFeedback({ job_id: jobId, reason }, token);
      setFeedbackNotes((prev) => ({
        ...prev,
        [jobId]:
          resp.personalization_note ||
          `Recorded: ${reason.replace(/_/g, " ")} — tune it anytime in Settings.`,
      }));
      setFeedbackMenu(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to record feedback",
      );
      setFeedbackMenu(null);
    } finally {
      setSendingFeedbackId(null);
    }
  };

  if (authLoading || (loading && !feed)) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-4 border-teal-500/20 border-t-teal-400 animate-spin" />
          <Sparkles className="h-6 w-6 text-teal-400 absolute inset-0 m-auto animate-pulse" />
        </div>
        <p className="mt-4 text-sm text-zinc-400 font-medium">
          Analyzing your skills & profile against open jobs...
        </p>
      </div>
    );
  }

  const filteredItems = (feed?.items || []).filter(
    (item) => item.match_score >= minMatchThreshold,
  );

  const getScoreColorClass = (score: number) => {
    if (score >= 70) {
      return {
        badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
        ring: "border-emerald-500/20 hover:border-emerald-500/40",
        bar: "bg-emerald-400",
        label: "High Alignment",
      };
    }
    if (score >= 40) {
      return {
        badge: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
        ring: "border-cyan-500/20 hover:border-cyan-500/40",
        bar: "bg-cyan-400",
        label: "Moderate Fit",
      };
    }
    return {
      badge: "bg-zinc-800 text-zinc-400 border-zinc-700",
      ring: "border-zinc-800/80 hover:border-zinc-700",
      bar: "bg-zinc-600",
      label: "Low Fit",
    };
  };

  return (
    <div className="min-h-screen bg-zinc-950 pb-20 text-zinc-100">
      {/* Top Hero Banner */}
      <div className="relative overflow-hidden border-b border-zinc-800 bg-gradient-to-b from-teal-950/30 via-zinc-950 to-zinc-950 py-10 px-4 sm:px-6 lg:px-8">
        <div className="absolute top-0 right-1/4 h-72 w-72 rounded-full bg-teal-500/5 blur-3xl" />
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-6 relative z-10">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-teal-500/10 px-3 py-1 text-xs font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30 mb-3">
              <Sparkles className="h-3.5 w-3.5 animate-pulse" />
              Content-Based Hybrid Engine
            </div>
            <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-white">
              AI Job Recommendations
            </h1>
            <p className="mt-2 text-zinc-400 max-w-2xl text-sm sm:text-base">
              Personalized matches computed from your skills, proficiency levels, and headline
              using TF-IDF cosine similarity and skill-gap diagnostics.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900/90 px-4 py-2.5 text-sm font-medium text-zinc-300 hover:bg-zinc-800 hover:text-white transition-all shadow-sm"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin text-teal-400" : ""}`} />
              Re-score Feed
            </button>
            <Link
              href="/profile"
              className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-teal-400 transition-all shadow-lg shadow-teal-500/20"
            >
              <UserCheck className="h-4 w-4" />
              Tune Profile Skills
            </Link>
          </div>
        </div>

        {/* Profile Completeness & Cold Start Callout */}
        {feed && (
          <div className="max-w-6xl mx-auto mt-8 relative z-10">
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 sm:p-5 backdrop-blur-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex-1 w-full sm:w-auto">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                    <TrendingUp className="h-3.5 w-3.5 text-teal-400" />
                    Profile Completeness: {feed.profile_completeness_score}%
                  </span>
                  <span className="text-xs font-medium text-zinc-400">
                    {feed.profile_completeness_score >= 80 ? "Optimized" : "Needs Attention"}
                  </span>
                </div>
                <div className="h-2 w-full rounded-full bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-teal-500 to-cyan-400 transition-all duration-700"
                    style={{ width: `${feed.profile_completeness_score}%` }}
                  />
                </div>
                {feed.recommendation_type === "cold_start" && (
                  <p className="mt-2 text-xs text-amber-400 flex items-center gap-1.5">
                    <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                    Cold-start mode active: Add skills to your profile to get high-accuracy tailored recommendations!
                  </p>
                )}

                {/* Phase 3: honest strategy/model provenance for this feed */}
                <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
                  <span
                    className="inline-flex items-center gap-1.5 rounded-full border border-zinc-700 bg-zinc-800/80 px-2.5 py-0.5 font-semibold text-zinc-300"
                    title="Ranking strategy used to score this feed"
                  >
                    <Layers className="h-3 w-3 text-teal-400" />
                    Strategy: {feed.strategy ?? feed.recommendation_strategy}
                  </span>
                  {feed.model_version && (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full border border-teal-500/30 bg-teal-500/10 px-2.5 py-0.5 font-semibold text-teal-300"
                      title="Learned model version used for re-ranking"
                    >
                      <Zap className="h-3 w-3" />
                      Model: {feed.model_version}
                    </span>
                  )}
                </div>
                {feed.personalization_note && (
                  <p className="mt-2 text-xs text-teal-300/90 flex items-start gap-1.5">
                    <Compass className="h-3.5 w-3.5 flex-shrink-0 mt-px" />
                    <span>{feed.personalization_note}</span>
                  </p>
                )}
              </div>

              {feed.profile_completeness_score < 80 && (
                <Link
                  href="/profile"
                  className="text-xs font-semibold text-teal-400 hover:text-teal-300 flex items-center gap-1 whitespace-nowrap pt-1 sm:pt-0"
                >
                  Improve score <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {error && (
          <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0" />
            <p>{error}</p>
          </div>
        )}

        {/* Filter Controls Bar */}
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-800/80 pb-4">
          <div className="flex items-center gap-2 text-sm text-zinc-400">
            <SlidersHorizontal className="h-4 w-4 text-teal-400" />
            <span>Showing <strong className="text-white">{filteredItems.length}</strong> ranked jobs</span>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400 font-medium">Filter by Fit:</span>
            <div className="inline-flex rounded-lg bg-zinc-900 p-1 border border-zinc-800 text-xs">
              <button
                onClick={() => setMinMatchThreshold(0)}
                className={`px-3 py-1 rounded-md transition-colors ${
                  minMatchThreshold === 0
                    ? "bg-zinc-800 text-white font-semibold"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                All Jobs
              </button>
              <button
                onClick={() => setMinMatchThreshold(35)}
                className={`px-3 py-1 rounded-md transition-colors ${
                  minMatchThreshold === 35
                    ? "bg-zinc-800 text-white font-semibold"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                ≥ 35% Match
              </button>
              <button
                onClick={() => setMinMatchThreshold(60)}
                className={`px-3 py-1 rounded-md transition-colors ${
                  minMatchThreshold === 60
                    ? "bg-zinc-800 text-white font-semibold"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                ≥ 60% Top Fits
              </button>
            </div>
          </div>
        </div>

        {/* Recommendation Cards Feed */}
        {filteredItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
            <Compass className="h-12 w-12 text-zinc-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-zinc-200">No jobs match this threshold</h3>
            <p className="mt-1 text-sm text-zinc-400 max-w-md mx-auto">
              Try switching filter to &quot;All Jobs&quot; or add more skills to your profile to expand matching criteria.
            </p>
            <button
              onClick={() => setMinMatchThreshold(0)}
              className="mt-4 rounded-lg bg-zinc-800 px-4 py-2 text-xs font-semibold text-zinc-200 hover:bg-zinc-700"
            >
              Reset Threshold Filter
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredItems.map((item, index) => {
              const scoreStyle = getScoreColorClass(item.match_score);
              return (
                <div
                  key={item.job.id}
                  className={`group relative rounded-2xl border bg-zinc-900/50 p-6 transition-all duration-200 ${scoreStyle.ring} hover:bg-zinc-900/80 shadow-md`}
                >
                  <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
                    {/* Left Column: Job Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        {/* Match Score Badge */}
                        <div
                          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold ${scoreStyle.badge}`}
                        >
                          <Zap className="h-3.5 w-3.5 fill-current" />
                          <span>{item.match_score}% Match</span>
                          <span className="opacity-70 font-normal">({scoreStyle.label})</span>
                        </div>

                        {/* Rank Badge */}
                        <span className="rounded-full bg-zinc-800/80 px-2.5 py-0.5 text-xs font-medium text-zinc-400">
                          #{index + 1} Best Match
                        </span>

                        {/* Phase 3: per-item rerank strategy / model version */}
                        {(item.model_version ||
                          (item.strategy ?? "deterministic") !== "deterministic") && (
                          <span
                            className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-0.5 text-xs font-semibold text-indigo-300"
                            title="Ranking strategy and model behind this item's score"
                          >
                            {[item.strategy, item.model_version].filter(Boolean).join(" · ")}
                          </span>
                        )}

                        {item.job.is_remote && (
                          <span className="rounded-full bg-teal-500/10 px-2.5 py-0.5 text-xs font-medium text-teal-400 border border-teal-500/20">
                            Remote
                          </span>
                        )}

                        {/* Phase 4 §14: "Powered by: <project> — <band>" */}
                        {item.job.project_relevance && (
                          <span
                            className="inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-0.5 text-xs font-semibold text-violet-300"
                            title="One of your projects powers this job's career family (plan §14)"
                          >
                            <Wrench className="h-3 w-3" />
                            {item.job.project_relevance}
                          </span>
                        )}
                      </div>

                      {/* Title */}
                      <Link
                        href={`/jobs/${item.job.id}`}
                        className="text-xl font-bold text-white group-hover:text-teal-400 transition-colors inline-block"
                      >
                        {item.job.title}
                      </Link>

                      {/* Company & Meta */}
                      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs sm:text-sm text-zinc-400">
                        <span className="font-semibold text-zinc-300">
                          {item.job.company.name}
                        </span>
                        <span className="flex items-center gap-1">
                          <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                          {item.job.location}
                        </span>
                        <span className="flex items-center gap-1">
                          <GraduationCap className="h-3.5 w-3.5 text-zinc-500" />
                          {item.job.experience_level.toUpperCase()}
                        </span>
                        {(item.job.salary_min || item.job.salary_max) && (
                          <span className="flex items-center gap-1 text-zinc-300 font-medium">
                            <DollarSign className="h-3.5 w-3.5 text-emerald-400" />
                            {item.job.salary_min?.toLocaleString()} - {item.job.salary_max?.toLocaleString()}{" "}
                            {item.job.salary_currency}
                          </span>
                        )}
                      </div>

                      {/* Description Snippet */}
                      <p className="mt-3 text-xs sm:text-sm text-zinc-400 line-clamp-2">
                        {item.job.requirements || item.job.description}
                      </p>

                      {/* Match Explanation Reasons */}
                      {item.match_reasons && item.match_reasons.length > 0 && (
                        <div className="mt-4 rounded-xl bg-zinc-950/60 border border-zinc-800/80 p-3 text-xs space-y-1.5">
                          <span className="font-semibold text-zinc-400 uppercase tracking-wider text-[10px] block mb-1">
                            Why You Match:
                          </span>
                          {item.match_reasons.map((reason, rIdx) => (
                            <div key={rIdx} className="flex items-center gap-2 text-zinc-300">
                              <CheckCircle2 className="h-3.5 w-3.5 text-teal-400 flex-shrink-0" />
                              <span>{reason}</span>
                            </div>
                          ))}
                          {item.explanation?.delta_note && (
                            <div className="flex items-center gap-2 text-amber-300 pt-1 border-t border-zinc-800/80 mt-1">
                              <TrendingUp className="h-3.5 w-3.5 flex-shrink-0" />
                              <span>{item.explanation.delta_note}</span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Skill Breakdown: Matched & Missing */}
                      <div className="mt-4 space-y-2">
                        {item.matched_skills.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-medium text-emerald-400 flex items-center gap-1 mr-1">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Matched Skills:
                            </span>
                            {item.matched_skills.map((skill) => (
                              <span
                                key={skill}
                                className="rounded-md bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300"
                              >
                                {skill}
                              </span>
                            ))}
                          </div>
                        )}

                        {item.missing_skills.length > 0 && (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-xs font-medium text-amber-400 flex items-center gap-1 mr-1">
                              <AlertCircle className="h-3.5 w-3.5" /> Missing Prerequisites:
                            </span>
                            {item.missing_skills.map((skill) => (
                              <span
                                key={skill}
                                className="rounded-md bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-300"
                              >
                                {skill}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right Column: Score Breakdown & Action CTA */}
                    <div className="flex lg:flex-col items-center lg:items-end justify-between lg:justify-center border-t lg:border-t-0 lg:border-l border-zinc-800/80 pt-4 lg:pt-0 lg:pl-6 gap-4 min-w-[180px]">
                      {/* Score Metrics pill */}
                      <div className="text-left lg:text-right space-y-1">
                        <div className="text-xs text-zinc-400">
                          Skill Match: <strong className="text-zinc-200">{item.skill_match_score}%</strong>
                        </div>
                        <div className="text-xs text-zinc-400">
                          Text Similarity: <strong className="text-zinc-200">{item.content_similarity_score}%</strong>
                        </div>
                      </div>

                      <div className="flex lg:flex-col gap-2">
                        <Link
                          href={`/gap/${item.job.id}`}
                          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-teal-500/50 hover:text-teal-300 transition-colors"
                        >
                          <Target className="h-3.5 w-3.5" />
                          Skill Gap
                        </Link>
                        <Link
                          href={`/roadmap?jobId=${item.job.id}`}
                          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-teal-500/50 hover:text-teal-300 transition-colors"
                        >
                          <Route className="h-3.5 w-3.5" />
                          Roadmap
                        </Link>

                        {/* Phase 4 §16: feedback → M4 weight + affinity update */}
                        <div className="relative">
                          <button
                            type="button"
                            onClick={() =>
                              setFeedbackMenu(
                                feedbackMenu === item.job.id ? null : item.job.id,
                              )
                            }
                            disabled={sendingFeedbackId === item.job.id}
                            aria-expanded={feedbackMenu === item.job.id}
                            className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-xs font-semibold text-zinc-300 hover:border-teal-500/50 hover:text-teal-300 transition-colors disabled:opacity-50"
                          >
                            <ThumbsDown className="h-3.5 w-3.5" />
                            {sendingFeedbackId === item.job.id
                              ? "Saving…"
                              : feedbackMenu === item.job.id
                                ? "Close"
                                : "Feedback"}
                          </button>
                          {feedbackMenu === item.job.id && (
                            <div className="absolute right-0 bottom-full z-30 mb-1 w-48 rounded-xl border border-zinc-700 bg-zinc-900 p-1 shadow-2xl shadow-black/50">
                              <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                                Why? (trains your model)
                              </p>
                              {FEEDBACK_REASONS.map((reason) => (
                                <button
                                  key={reason.value}
                                  type="button"
                                  onClick={() =>
                                    handleFeedback(item.job.id, reason.value)
                                  }
                                  className="block w-full rounded-lg px-2.5 py-1.5 text-left text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors"
                                >
                                  {reason.label}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {feedbackNotes[item.job.id] && (
                        <p className="max-w-[200px] text-[11px] leading-snug text-teal-400 lg:text-right">
                          {feedbackNotes[item.job.id]}
                        </p>
                      )}

                      <Link
                        href={`/jobs/${item.job.id}`}
                        className="inline-flex items-center gap-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-zinc-950 font-semibold px-4 py-2.5 text-sm transition-all shadow-md shadow-teal-500/20"
                      >
                        View & Apply
                        <ChevronRight className="h-4 w-4" />
                      </Link>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
