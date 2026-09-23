"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getJobs } from "@/lib/api";
import { JobDetail } from "@/lib/types";
import {
  ArrowUpDown,
  Briefcase,
  Building2,
  Calendar,
  Compass,
  DollarSign,
  MapPin,
  Search,
  Sparkles,
  Wifi,
  X,
} from "lucide-react";

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);

  // Search & Filter state
  const [q, setQ] = useState("");
  const [location, setLocation] = useState("");
  const [isRemote, setIsRemote] = useState<boolean | undefined>(undefined);
  const [employmentType, setEmploymentType] = useState<string>("");
  const [experienceLevel, setExperienceLevel] = useState<string>("");
  const [skillFilter, setSkillFilter] = useState<string>("");
  const [sortBy, setSortBy] = useState<"relevance" | "date" | "salary">("relevance");

  const loadJobs = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getJobs({
        q: q.trim() || undefined,
        location: location.trim() || undefined,
        is_remote: isRemote,
        employment_type: employmentType || undefined,
        experience_level: experienceLevel || undefined,
        skill: skillFilter.trim() || undefined,
        sort_by: sortBy,
        page,
      });
      setJobs(data.items);
      setTotal(data.total);
    } catch {
      setJobs([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, [q, location, isRemote, employmentType, experienceLevel, skillFilter, sortBy, page]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadJobs();
  };

  const clearAllFilters = () => {
    setQ("");
    setLocation("");
    setIsRemote(undefined);
    setEmploymentType("");
    setExperienceLevel("");
    setSkillFilter("");
    setSortBy("relevance");
    setPage(1);
  };

  const hasActiveFilters = Boolean(
    q || location || isRemote !== undefined || employmentType || experienceLevel || skillFilter
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="border-b border-zinc-800/80 pb-6">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
          <Compass className="h-4 w-4" />
          Full-Text Search & Catalog
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Search Open Positions
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Instant keyword, title, skill, and multi-parameter search backed by PostgreSQL GIN indexing.
        </p>
      </div>

      {/* Filter & Search Bar */}
      <form
        onSubmit={handleSearchSubmit}
        className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5 backdrop-blur shadow-xl space-y-4"
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {/* Keyword Search Input */}
          <div className="relative lg:col-span-2">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
              <Search className="h-4 w-4" />
            </div>
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search by keywords, phrases (e.g. 'machine learning', python, distributed)..."
              className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-8 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
            />
            {q && (
              <button
                type="button"
                onClick={() => setQ("")}
                className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-zinc-500 hover:text-zinc-300"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* Location Input */}
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
              <MapPin className="h-4 w-4" />
            </div>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Location (city, state)"
              className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
            />
          </div>

          {/* Sort Selector */}
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
              <ArrowUpDown className="h-4 w-4" />
            </div>
            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value as "relevance" | "date" | "salary");
                setPage(1);
              }}
              className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
            >
              <option value="relevance">Sort: Most Relevant</option>
              <option value="date">Sort: Newest First</option>
              <option value="salary">Sort: Highest Salary</option>
            </select>
          </div>
        </div>

        {/* Secondary Filter Line */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-zinc-800/60">
          <select
            value={employmentType}
            onChange={(e) => {
              setEmploymentType(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-xs text-zinc-300 focus:border-teal-500 focus:outline-none"
          >
            <option value="">All Employment Types</option>
            <option value="full_time">Full-Time</option>
            <option value="part_time">Part-Time</option>
            <option value="contract">Contract</option>
            <option value="internship">Internship</option>
          </select>

          <select
            value={experienceLevel}
            onChange={(e) => {
              setExperienceLevel(e.target.value);
              setPage(1);
            }}
            className="rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-xs text-zinc-300 focus:border-teal-500 focus:outline-none"
          >
            <option value="">All Seniority Levels</option>
            <option value="entry">Entry Level</option>
            <option value="mid">Mid Level</option>
            <option value="senior">Senior</option>
            <option value="lead">Lead</option>
            <option value="executive">Executive</option>
          </select>

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-zinc-300">
              <input
                type="checkbox"
                checked={isRemote === true}
                onChange={(e) => {
                  setIsRemote(e.target.checked ? true : undefined);
                  setPage(1);
                }}
                className="rounded border-zinc-700 bg-zinc-900 text-teal-500 focus:ring-teal-500"
              />
              <span className="flex items-center gap-1">
                <Wifi className="h-3.5 w-3.5 text-teal-400" />
                Remote Only
              </span>
            </label>

            <button
              type="submit"
              className="rounded-lg bg-teal-500 px-4 py-1.5 text-xs font-semibold text-zinc-950 shadow-sm shadow-teal-500/20 hover:bg-teal-400 active:scale-[0.98] transition-all"
            >
              Search
            </button>
          </div>
        </div>

        {/* Active Filter Chips */}
        {hasActiveFilters && (
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-zinc-800/40 text-xs">
            <span className="text-zinc-500 font-medium">Active Filters:</span>

            {q && (
              <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-teal-300 ring-1 ring-teal-500/30">
                Query: &quot;{q}&quot;
                <button type="button" onClick={() => setQ("")} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            {location && (
              <span className="inline-flex items-center gap-1 rounded-full bg-zinc-800 px-2.5 py-0.5 text-zinc-300">
                Location: {location}
                <button type="button" onClick={() => setLocation("")} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            {isRemote && (
              <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-teal-300 ring-1 ring-teal-500/30">
                Remote Only
                <button type="button" onClick={() => setIsRemote(undefined)} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            {employmentType && (
              <span className="inline-flex items-center gap-1 rounded-full bg-zinc-800 px-2.5 py-0.5 text-zinc-300 capitalize">
                {employmentType.replace("_", "-")}
                <button type="button" onClick={() => setEmploymentType("")} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            {experienceLevel && (
              <span className="inline-flex items-center gap-1 rounded-full bg-zinc-800 px-2.5 py-0.5 text-zinc-300 capitalize">
                {experienceLevel}
                <button type="button" onClick={() => setExperienceLevel("")} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            {skillFilter && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2.5 py-0.5 text-indigo-300 ring-1 ring-indigo-500/30">
                Skill: {skillFilter}
                <button type="button" onClick={() => setSkillFilter("")} className="hover:text-white">
                  <X className="h-3 w-3" />
                </button>
              </span>
            )}

            <button
              type="button"
              onClick={clearAllFilters}
              className="text-xs text-rose-400 hover:text-rose-300 ml-auto underline-offset-4 hover:underline"
            >
              Reset all
            </button>
          </div>
        )}
      </form>

      {/* Meta Bar */}
      <div className="mt-6 flex items-center justify-between text-xs text-zinc-400">
        <span>
          Found <strong className="text-white">{total}</strong> position(s)
          {q && <span> for &quot;{q}&quot;</span>}
        </span>
        <span className="capitalize">
          Ordering: {sortBy === "relevance" ? "Weighted Relevance" : sortBy === "salary" ? "Highest Compensation" : "Recent Date"}
        </span>
      </div>

      {/* Results List */}
      {isLoading ? (
        <div className="mt-8 flex justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        </div>
      ) : jobs.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-zinc-800/80 bg-zinc-900/30 p-16 text-center">
          <Briefcase className="mx-auto h-10 w-10 text-zinc-600" />
          <h3 className="mt-3 text-base font-semibold text-white">No matching opportunities found</h3>
          <p className="mt-1 text-xs text-zinc-400 max-w-sm mx-auto">
            Try adjusting your search terms, broadening keywords, or clearing remote/salary filters.
          </p>
          <button
            type="button"
            onClick={clearAllFilters}
            className="mt-4 rounded-lg bg-zinc-800 px-4 py-2 text-xs font-medium text-zinc-200 hover:bg-zinc-700"
          >
            Clear All Filters
          </button>
        </div>
      ) : (
        <div className="mt-6 space-y-4">
          {jobs.map((job) => (
            <Link
              key={job.id}
              href={`/jobs/${job.id}`}
              className="group block rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur hover:border-zinc-700 hover:bg-zinc-900/70 transition-all shadow-md"
            >
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1 text-xs font-semibold text-zinc-400">
                      <Building2 className="h-3.5 w-3.5 text-zinc-500" />
                      {job.company.name}
                    </span>

                    {job.is_remote && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2 py-0.5 text-[11px] font-medium text-teal-300 ring-1 ring-teal-500/30">
                        <Wifi className="h-2.5 w-2.5" />
                        Remote
                      </span>
                    )}

                    <span className="rounded bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-300 capitalize">
                      {job.experience_level}
                    </span>

                    {job.relevance_score !== null && job.relevance_score !== undefined && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-teal-400/10 px-2 py-0.5 text-[11px] font-semibold text-teal-300 ring-1 ring-teal-400/30">
                        <Sparkles className="h-2.5 w-2.5 text-teal-400" />
                        {Math.min(100, Math.round(job.relevance_score))}% Match
                      </span>
                    )}
                  </div>

                  <h2 className="mt-2 text-xl font-bold text-white group-hover:text-teal-300 transition-colors">
                    {job.title}
                  </h2>

                  {/* Highlighted snippet preview if available */}
                  {job.snippet ? (
                    <div
                      className="mt-2 text-xs leading-relaxed text-zinc-300"
                      dangerouslySetInnerHTML={{ __html: `...${job.snippet}...` }}
                    />
                  ) : (
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-zinc-400">
                      {job.description}
                    </p>
                  )}
                </div>

                <div className="sm:text-right shrink-0">
                  {job.salary_min || job.salary_max ? (
                    <div className="flex items-center gap-1 text-base font-bold text-white sm:justify-end">
                      <DollarSign className="h-4 w-4 text-emerald-400" />
                      <span>
                        {job.salary_min ? `$${(job.salary_min / 1000).toFixed(0)}k` : ""}
                        {job.salary_min && job.salary_max ? " - " : ""}
                        {job.salary_max ? `$${(job.salary_max / 1000).toFixed(0)}k` : ""}
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-zinc-500">Competitive salary</span>
                  )}
                  <div className="mt-1 flex items-center gap-1 text-xs text-zinc-500 sm:justify-end">
                    <MapPin className="h-3 w-3" />
                    <span>{job.location}</span>
                  </div>
                </div>
              </div>

              {/* Skills Chips */}
              {job.skills && job.skills.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2 pt-4 border-t border-zinc-800/60">
                  <span className="text-[11px] uppercase tracking-wider text-zinc-500">
                    Required:
                  </span>
                  {job.skills.map((sk, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        setSkillFilter(sk.skill_name);
                        setPage(1);
                      }}
                      className="inline-flex items-center gap-1 rounded bg-zinc-800/80 px-2 py-0.5 text-xs text-zinc-300 hover:bg-teal-500/20 hover:text-teal-200 transition-colors"
                    >
                      <Sparkles className="h-2.5 w-2.5 text-teal-400" />
                      {sk.skill_name}
                    </button>
                  ))}
                  <div className="ml-auto flex items-center gap-1 text-[11px] text-zinc-500">
                    <Calendar className="h-3 w-3" />
                    <span>{new Date(job.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
