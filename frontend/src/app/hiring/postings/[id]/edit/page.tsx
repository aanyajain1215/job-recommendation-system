"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { getJobDetail, getSkills, updateJob } from "@/lib/api";
import {
  EmploymentType,
  ExperienceLevel,
  JobDetail,
  JobSkillInput,
  Skill,
} from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { ArrowLeft, Plus, Sparkles, Trash2 } from "lucide-react";

const CANONICAL_FAMILIES = [
  "Backend Engineering",
  "Cybersecurity",
  "Data Analytics",
  "Data Science",
  "DevOps Engineering",
  "Frontend Engineering",
  "Machine Learning Engineering",
  "Software Engineering",
];

export default function EditPostingPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params?.id as string;
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // form state
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
  const [family, setFamily] = useState("");
  const [skills, setSkills] = useState<JobSkillInput[]>([]);

  // skill picker
  const [skillSearch, setSkillSearch] = useState("");
  const [suggestions, setSuggestions] = useState<Skill[]>([]);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      setError(null);
      const job: JobDetail = await getJobDetail(jobId);
      setTitle(job.title);
      setDescription(job.description);
      setRequirements(job.requirements ?? "");
      setEmploymentType(job.employment_type);
      setExperienceLevel(job.experience_level);
      setLocation(job.location);
      setIsRemote(job.is_remote);
      setSalaryMin(job.salary_min ?? "");
      setSalaryMax(job.salary_max ?? "");
      setSalaryCurrency(job.salary_currency || "INR");
      setFamily(job.family ?? "");
      setSkills(
        (job.skills ?? []).map((s) => ({
          skill_name: s.skill_name,
          is_required: s.is_required,
          importance_weight: s.importance_weight,
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load posting");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  useEffect(() => {
    if (skillSearch.trim().length > 1) {
      getSkills(skillSearch.trim()).then(setSuggestions).catch(() => setSuggestions([]));
    } else {
      setSuggestions([]);
    }
  }, [skillSearch]);

  const addSkill = (name: string, required: boolean) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (skills.some((s) => s.skill_name.toLowerCase() === trimmed.toLowerCase())) {
      toast.info("That skill is already listed.");
      return;
    }
    setSkills([...skills, { skill_name: trimmed, is_required: required, importance_weight: 1.0 }]);
    setSkillSearch("");
    setSuggestions([]);
  };

  const toggleRequired = (index: number) => {
    setSkills((prev) =>
      prev.map((s, i) => (i === index ? { ...s, is_required: !s.is_required } : s)),
    );
  };

  const removeSkill = (index: number) => setSkills((prev) => prev.filter((_, i) => i !== index));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    if (!title.trim() || !description.trim() || !location.trim()) {
      setError("Title, description and location are required.");
      return;
    }
    if (salaryMin !== "" && salaryMax !== "" && Number(salaryMin) > Number(salaryMax)) {
      setError("Minimum salary cannot exceed maximum salary.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateJob(
        jobId,
        {
          title: title.trim(),
          description: description.trim(),
          requirements: requirements.trim() || undefined,
          employment_type: employmentType,
          experience_level: experienceLevel,
          location: location.trim(),
          is_remote: isRemote,
          salary_min: salaryMin === "" ? null : Number(salaryMin),
          salary_max: salaryMax === "" ? null : Number(salaryMax),
          salary_currency: salaryCurrency,
          skills,
          // only send family when the employer typed one, so leaving it
          // blank can never accidentally clear an existing family tag
          ...(family.trim() ? { family: family.trim() } : {}),
        },
        token,
      );
      toast.success("Posting updated.");
      router.push(`/hiring/postings/${jobId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save changes");
      setSaving(false);
    }
  };

  if (authLoading || !ready) return <EmployerLoading />;

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="h-8 w-48 animate-pulse rounded bg-zinc-900" />
        <div className="mt-6 h-96 animate-pulse rounded-xl bg-zinc-900/60" />
      </div>
    );
  }

  const inputCls =
    "mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none";
  const labelCls =
    "block text-xs font-medium uppercase tracking-wider text-zinc-400";

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
      <Link
        href={`/hiring/postings/${jobId}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-400 hover:text-zinc-200"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to posting
      </Link>

      <h1 className="mt-4 text-3xl font-bold tracking-tight text-zinc-100">Edit posting</h1>
      <p className="mt-1 text-sm text-zinc-400">
        Changes apply immediately to your live listing.
      </p>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <form onSubmit={onSubmit} className="mt-8 space-y-6">
        <div>
          <label className={labelCls}>Job Title *</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputCls}
            placeholder="e.g. Senior Distributed Systems Engineer"
            required
            minLength={3}
          />
        </div>

        <div>
          <label className={labelCls}>Description *</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={6}
            className={inputCls}
            placeholder="What will this person do and own?"
            required
            minLength={10}
          />
        </div>

        <div>
          <label className={labelCls}>Requirements</label>
          <textarea
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            rows={4}
            className={inputCls}
            placeholder="Experience, education, certifications…"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelCls}>Employment Type</label>
            <select
              value={employmentType}
              onChange={(e) => setEmploymentType(e.target.value as EmploymentType)}
              className={inputCls}
            >
              <option value="full_time">Full-Time</option>
              <option value="part_time">Part-Time</option>
              <option value="contract">Contract</option>
              <option value="internship">Internship</option>
              <option value="temporary">Temporary</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>Experience Level</label>
            <select
              value={experienceLevel}
              onChange={(e) => setExperienceLevel(e.target.value as ExperienceLevel)}
              className={inputCls}
            >
              <option value="entry">Entry Level</option>
              <option value="mid">Mid Level</option>
              <option value="senior">Senior</option>
              <option value="lead">Lead</option>
              <option value="executive">Executive</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelCls}>Location *</label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className={inputCls}
              placeholder="e.g. Bengaluru, India"
              required
              minLength={2}
            />
          </div>
          <div className="flex items-end pb-2">
            <label className="flex cursor-pointer items-center gap-2.5 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={isRemote}
                onChange={(e) => setIsRemote(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-700 bg-zinc-900 text-teal-500 focus:ring-teal-500"
              />
              This role is remote
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className={labelCls}>Salary min</label>
            <input
              type="number"
              value={salaryMin}
              onChange={(e) => setSalaryMin(e.target.value === "" ? "" : Number(e.target.value))}
              className={inputCls}
              placeholder="0"
              min={0}
            />
          </div>
          <div>
            <label className={labelCls}>Salary max</label>
            <input
              type="number"
              value={salaryMax}
              onChange={(e) => setSalaryMax(e.target.value === "" ? "" : Number(e.target.value))}
              className={inputCls}
              placeholder="0"
              min={0}
            />
          </div>
          <div>
            <label className={labelCls}>Currency</label>
            <input
              value={salaryCurrency}
              onChange={(e) => setSalaryCurrency(e.target.value.toUpperCase())}
              className={inputCls}
              placeholder="INR"
              maxLength={10}
            />
          </div>
        </div>

        <div>
          <label className={labelCls}>Job family</label>
          <input
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            list="canonical-families"
            className={inputCls}
            placeholder="e.g. Backend Engineering"
          />
          <datalist id="canonical-families">
            {CANONICAL_FAMILIES.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
          <p className="mt-1.5 text-xs text-zinc-500">
            Leave blank to keep the current family. Family drives matching, so pick the closest
            one.
          </p>
        </div>

        {/* Skills */}
        <div>
          <label className={labelCls}>Skills</label>
          <input
            value={skillSearch}
            onChange={(e) => setSkillSearch(e.target.value)}
            className={inputCls}
            placeholder="Search and add a skill (e.g. Kafka)"
          />
          {suggestions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {suggestions.slice(0, 8).map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => addSkill(s.name, true)}
                  className="rounded-full border border-zinc-700 bg-zinc-900/60 px-2.5 py-1 text-xs text-zinc-300 hover:border-teal-500/50 hover:text-teal-300"
                >
                  <Plus className="mr-1 inline h-3 w-3" />
                  {s.name}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={() => addSkill(skillSearch, true)}
            disabled={!skillSearch.trim()}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            Add custom skill
          </button>

          {skills.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {skills.map((s, i) => (
                <li
                  key={`${s.skill_name}-${i}`}
                  className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2"
                >
                  <button
                    type="button"
                    onClick={() => toggleRequired(i)}
                    title="Toggle required / nice-to-have"
                    className="flex items-center gap-2 text-left"
                  >
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${
                        s.is_required
                          ? "bg-teal-500/10 text-teal-300 ring-teal-500/30"
                          : "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30"
                      }`}
                    >
                      {s.is_required ? "Required" : "Nice to have"}
                    </span>
                    <span className="text-sm text-zinc-200">{s.skill_name}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => removeSkill(i)}
                    className="text-zinc-500 hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500">
            <Sparkles className="h-3.5 w-3.5 text-teal-500" />
            Click a skill label to toggle required vs nice-to-have.
          </p>
        </div>

        <div className="flex items-center gap-3 border-t border-zinc-800/70 pt-6">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          <Link
            href={`/hiring/postings/${jobId}`}
            className="rounded-xl border border-zinc-700 bg-zinc-900/60 px-5 py-3 text-sm font-semibold text-zinc-200 hover:bg-zinc-800"
          >
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
