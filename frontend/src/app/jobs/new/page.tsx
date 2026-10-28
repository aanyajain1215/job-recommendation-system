"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { createJob, getSkills } from "@/lib/api";
import {
  EmploymentType,
  ExperienceLevel,
  JobSkillInput,
  Skill,
} from "@/lib/types";
import {
  ArrowLeft,
  Building2,
  DollarSign,
  MapPin,
  Plus,
  PlusCircle,
  Sparkles,
  Trash2,
} from "lucide-react";

export default function NewJobPage() {
  const router = useRouter();
  const { user, token, isLoading: isAuthLoading } = useAuth();

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form fields
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState("");
  const [employmentType, setEmploymentType] = useState<EmploymentType>("full_time");
  const [experienceLevel, setExperienceLevel] = useState<ExperienceLevel>("mid");
  const [location, setLocation] = useState("");
  const [isRemote, setIsRemote] = useState(false);
  const [salaryMin, setSalaryMin] = useState<number | "">("");
  const [salaryMax, setSalaryMax] = useState<number | "">("");
  const [salaryCurrency, setSalaryCurrency] = useState("INR");

  // Skills
  const [skills, setSkills] = useState<JobSkillInput[]>([]);
  const [skillSearch, setSkillSearch] = useState("");
  const [suggestedSkills, setSuggestedSkills] = useState<Skill[]>([]);

  useEffect(() => {
    if (!isAuthLoading && (!user || (user.role !== "employer" && user.role !== "admin"))) {
      router.push("/dashboard");
    }
  }, [user, isAuthLoading, router]);

  useEffect(() => {
    if (skillSearch.trim().length > 1) {
      getSkills(skillSearch.trim()).then((items) => setSuggestedSkills(items));
    } else {
      setSuggestedSkills([]);
    }
  }, [skillSearch]);

  const handleAddSkill = (skillName: string) => {
    const trimmed = skillName.trim();
    if (!trimmed) return;
    if (skills.some((s) => s.skill_name.toLowerCase() === trimmed.toLowerCase())) {
      setSkillSearch("");
      setSuggestedSkills([]);
      return;
    }

    setSkills([
      ...skills,
      { skill_name: trimmed, is_required: true, importance_weight: 1.0 },
    ]);
    setSkillSearch("");
    setSuggestedSkills([]);
  };

  const handleRemoveSkill = (index: number) => {
    setSkills(skills.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;

    if (!title.trim() || !description.trim() || !location.trim()) {
      setError("Title, location, and description are required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const job = await createJob(
        {
          title,
          description,
          requirements: requirements.trim() || undefined,
          employment_type: employmentType,
          experience_level: experienceLevel,
          location,
          is_remote: isRemote,
          salary_min: salaryMin === "" ? null : Number(salaryMin),
          salary_max: salaryMax === "" ? null : Number(salaryMax),
          salary_currency: salaryCurrency,
          skills,
        },
        token
      );
      router.push(`/jobs/${job.id}`);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to create job posting.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="mb-6">
        <button
          type="button"
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-100 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back
        </button>
      </div>

      <div className="border-b border-zinc-800/80 pb-6">
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 flex items-center gap-2.5">
          <Building2 className="h-7 w-7 text-indigo-400" />
          Create Structured Job Posting
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Structured roles power high-accuracy candidate generation and re-ranking across the platform.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="mt-8 space-y-8">
        {/* Core Job Details */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-5">
          <h2 className="text-lg font-semibold text-zinc-100">Job Overview</h2>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Job Title *
            </label>
            <input
              type="text"
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Senior Distributed Systems Engineer"
              className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Employment Type
              </label>
              <select
                value={employmentType}
                onChange={(e) => setEmploymentType(e.target.value as EmploymentType)}
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
              >
                <option value="full_time">Full-Time</option>
                <option value="part_time">Part-Time</option>
                <option value="contract">Contract</option>
                <option value="internship">Internship</option>
                <option value="temporary">Temporary</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Experience Level
              </label>
              <select
                value={experienceLevel}
                onChange={(e) => setExperienceLevel(e.target.value as ExperienceLevel)}
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
              >
                <option value="entry">Entry Level</option>
                <option value="mid">Mid Level</option>
                <option value="senior">Senior</option>
                <option value="lead">Lead</option>
                <option value="executive">Executive</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Location *
              </label>
              <div className="relative mt-1.5 rounded-lg">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
                  <MapPin className="h-4 w-4" />
                </div>
                <input
                  type="text"
                  required
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g. San Francisco, CA or Remote"
                  className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex items-center pt-6">
              <label className="flex items-center gap-2.5 cursor-pointer text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={isRemote}
                  onChange={(e) => setIsRemote(e.target.checked)}
                  className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 text-indigo-500 focus:ring-indigo-500"
                />
                <span>Remote / Distributed position</span>
              </label>
            </div>
          </div>
        </section>

        {/* Compensation */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-4">
          <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <DollarSign className="h-5 w-5 text-indigo-400" />
            Compensation & Salary Band
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Minimum Annual Salary
              </label>
              <input
                type="number"
                step="5000"
                min="0"
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="e.g. 120000"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Maximum Annual Salary
              </label>
              <input
                type="number"
                step="5000"
                min="0"
                value={salaryMax}
                onChange={(e) => setSalaryMax(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="e.g. 160000"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Currency
              </label>
              <input
                type="text"
                value={salaryCurrency}
                onChange={(e) => setSalaryCurrency(e.target.value.toUpperCase())}
                placeholder="USD"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
              />
            </div>
          </div>
        </section>

        {/* Required Skills & Importance */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-indigo-400" />
                Required Skills & Weights
              </h2>
              <p className="mt-1 text-xs text-zinc-400">
                Skills tagged here drive the LightGBM re-ranking algorithm scoring.
              </p>
            </div>
            <span className="text-xs text-indigo-400 font-medium">
              {skills.length} skills required
            </span>
          </div>

          <div className="relative">
            <div className="flex gap-2">
              <input
                type="text"
                value={skillSearch}
                onChange={(e) => setSkillSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAddSkill(skillSearch);
                  }
                }}
                placeholder="Search or add skill (e.g. Python, Machine Learning, PostgreSQL)..."
                className="block flex-1 rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => handleAddSkill(skillSearch)}
                className="inline-flex items-center gap-1 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700"
              >
                <Plus className="h-4 w-4" />
                Add
              </button>
            </div>

            {suggestedSkills.length > 0 && (
              <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900 shadow-xl">
                {suggestedSkills.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => handleAddSkill(s.name)}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-zinc-200 hover:bg-indigo-500/20 hover:text-zinc-100"
                  >
                    <span>{s.name}</span>
                    <span className="text-xs text-zinc-500 uppercase">{s.category}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2 pt-2">
            {skills.map((sk, idx) => (
              <div
                key={idx}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950/50 p-3"
              >
                <span className="font-semibold text-sm text-zinc-100">{sk.skill_name}</span>

                <div className="flex items-center gap-4 text-xs">
                  <label className="flex items-center gap-1.5 text-zinc-300">
                    <input
                      type="checkbox"
                      checked={sk.is_required}
                      onChange={(e) => {
                        const copy = [...skills];
                        copy[idx].is_required = e.target.checked;
                        setSkills(copy);
                      }}
                      className="rounded border-zinc-700 bg-zinc-900 text-indigo-500"
                    />
                    <span>Must-have</span>
                  </label>

                  <div className="flex items-center gap-2 text-zinc-400">
                    <span>Weight:</span>
                    <input
                      type="range"
                      min="0.5"
                      max="3.0"
                      step="0.1"
                      value={sk.importance_weight}
                      onChange={(e) => {
                        const copy = [...skills];
                        copy[idx].importance_weight = Number(e.target.value);
                        setSkills(copy);
                      }}
                      className="w-24 accent-indigo-500 cursor-pointer"
                    />
                    <span className="font-mono text-zinc-200">{sk.importance_weight}x</span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveSkill(idx)}
                    className="text-zinc-500 hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Descriptions */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur space-y-4">
          <h2 className="text-lg font-semibold text-zinc-100">Role Description & Requirements</h2>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Detailed Description *
            </label>
            <textarea
              required
              rows={6}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Outline role responsibilities, team structure, and projects..."
              className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Requirements & Qualifications
            </label>
            <textarea
              rows={4}
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
              placeholder="Specify years of experience, technical foundations, and background..."
              className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>
        </section>

        <div className="flex justify-end pt-4">
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-500 px-6 py-3 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 hover:bg-indigo-400 disabled:opacity-50 active:scale-[0.98] transition-all"
          >
            {isSubmitting ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <PlusCircle className="h-4 w-4" />
            )}
            Publish Job Listing
          </button>
        </div>
      </form>
    </div>
  );
}
