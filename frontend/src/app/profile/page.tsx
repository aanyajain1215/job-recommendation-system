"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  getMyProfile,
  getSkills,
  updateMyProfile,
  uploadResume,
} from "@/lib/api";
import {
  EducationItem,
  ExperienceItem,
  ProfileDetail,
  ProfileSkillItem,
  Skill,
} from "@/lib/types";
import {
  Briefcase,
  CheckCircle2,
  FileCheck,
  GraduationCap,
  Plus,
  Save,
  Trash2,
  Upload,
  User as UserIcon,
} from "lucide-react";

export default function ProfilePage() {
  const router = useRouter();
  const { user, token, isLoading: isAuthLoading } = useAuth();

  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Form states
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [headline, setHeadline] = useState("");
  const [bio, setBio] = useState("");
  const [location, setLocation] = useState("");
  const [phone, setPhone] = useState("");
  const [yearsOfExp, setYearsOfExp] = useState<number | "">("");

  // Skills
  const [skills, setSkills] = useState<ProfileSkillItem[]>([]);
  const [skillSearch, setSkillSearch] = useState("");
  const [suggestedSkills, setSuggestedSkills] = useState<Skill[]>([]);

  // Education & Experience
  const [education, setEducation] = useState<EducationItem[]>([]);
  const [experience, setExperience] = useState<ExperienceItem[]>([]);

  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.push("/login");
      return;
    }

    if (token) {
      getMyProfile(token)
        .then((data) => {
          setProfile(data);
          setFirstName(data.first_name || "");
          setLastName(data.last_name || "");
          setHeadline(data.headline || "");
          setBio(data.bio || "");
          setLocation(data.location || "");
          setPhone(data.phone || "");
          setYearsOfExp(data.years_of_experience ?? "");
          setSkills(data.skills || []);
          setEducation(data.education || []);
          setExperience(data.work_experience || []);
        })
        .catch((err) => {
          setMessage({ type: "error", text: err.message });
        })
        .finally(() => setIsLoading(false));
    }
  }, [user, token, isAuthLoading, router]);

  // Autocomplete skills search
  useEffect(() => {
    if (skillSearch.trim().length > 1) {
      getSkills(skillSearch.trim()).then((items) => setSuggestedSkills(items));
    } else {
      setSuggestedSkills([]);
    }
  }, [skillSearch]);

  const handleAddSkill = (skillName: string, category?: string | null) => {
    const trimmed = skillName.trim();
    if (!trimmed) return;
    if (skills.some((s) => s.skill_name.toLowerCase() === trimmed.toLowerCase())) {
      setSkillSearch("");
      setSuggestedSkills([]);
      return;
    }

    setSkills([
      ...skills,
      {
        skill_name: trimmed,
        category: category || undefined,
        proficiency_level: "intermediate",
        years_of_experience: 2,
      },
    ]);
    setSkillSearch("");
    setSuggestedSkills([]);
  };

  const handleRemoveSkill = (indexToRemove: number) => {
    setSkills(skills.filter((_, idx) => idx !== indexToRemove));
  };

  const handleUpdateSkill = (
    index: number,
    field: "proficiency_level" | "years_of_experience",
    value: unknown
  ) => {
    const updated = [...skills];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    updated[index] = { ...updated[index], [field]: value as any };
    setSkills(updated);
  };

  const handleAddEducation = () => {
    setEducation([
      ...education,
      { degree: "", institution: "", field_of_study: "", start_year: 2020, end_year: 2024 },
    ]);
  };

  const handleAddExperience = () => {
    setExperience([
      ...experience,
      { title: "", company: "", location: "", start_date: "", end_date: "", description: "" },
    ]);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !token) return;

    setIsUploading(true);
    setMessage(null);

    try {
      const res = await uploadResume(file, token);
      if (profile) {
        setProfile({ ...profile, resume_url: res.resume_url });
      }
      setMessage({ type: "success", text: `Resume '${file.name}' uploaded successfully!` });
    } catch (err: unknown) {
      if (err instanceof Error) {
        setMessage({ type: "error", text: err.message });
      }
    } finally {
      setIsUploading(false);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;

    setIsSaving(true);
    setMessage(null);

    try {
      const res = await updateMyProfile(
        {
          first_name: firstName,
          last_name: lastName,
          headline,
          bio,
          location,
          phone,
          years_of_experience: yearsOfExp === "" ? null : Number(yearsOfExp),
          skills,
          education,
          work_experience: experience,
        },
        token
      );
      setProfile(res);
      setMessage({ type: "success", text: "Profile updated successfully!" });
    } catch (err: unknown) {
      if (err instanceof Error) {
        setMessage({ type: "error", text: err.message });
      }
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-12">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-zinc-800/80 pb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-2">
            <UserIcon className="h-7 w-7 text-teal-400" />
            Profile Builder & Resume
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Define your skills, background, and upload your resume to sharpen AI recommendations.
          </p>
        </div>

        <button
          type="button"
          onClick={handleSaveProfile}
          disabled={isSaving}
          className="inline-flex items-center gap-2 rounded-lg bg-teal-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 shadow-md shadow-teal-500/20 hover:bg-teal-400 disabled:opacity-50 active:scale-[0.98] transition-all"
        >
          {isSaving ? (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-950 border-t-transparent" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save Profile
        </button>
      </div>

      {message && (
        <div
          className={`mt-6 rounded-lg p-4 text-sm ${
            message.type === "success"
              ? "border border-teal-500/30 bg-teal-500/10 text-teal-300"
              : "border border-rose-500/30 bg-rose-500/10 text-rose-300"
          }`}
        >
          {message.text}
        </div>
      )}

      <form onSubmit={handleSaveProfile} className="mt-8 space-y-8">
        {/* Resume Upload Card */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <FileCheck className="h-5 w-5 text-teal-400" />
            Resume Document
          </h2>
          <p className="mt-1 text-xs text-zinc-400">
            Upload PDF, DOCX, or TXT (up to 10MB). Stored securely and ready for Phase 2 parsing.
          </p>

          <div className="mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-xl border border-dashed border-zinc-700 bg-zinc-950/40 p-5">
            <div>
              {profile?.resume_url ? (
                <div className="flex items-center gap-2 text-sm text-teal-400 font-medium">
                  <CheckCircle2 className="h-4 w-4" />
                  Resume active on profile
                </div>
              ) : (
                <p className="text-sm text-zinc-400">No resume uploaded yet.</p>
              )}
              <p className="text-xs text-zinc-500 mt-1">Accepted: .pdf, .docx, .txt (max 10MB)</p>
            </div>

            <div className="flex items-center gap-3">
              <label className="cursor-pointer inline-flex items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition-colors">
                {isUploading ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-transparent" />
                ) : (
                  <Upload className="h-4 w-4 text-zinc-400" />
                )}
                <span>Upload New Resume</span>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  className="hidden"
                  onChange={handleFileUpload}
                  disabled={isUploading}
                />
              </label>

              {profile?.resume_url && (
                <a
                  href={`http://localhost:8000${profile.resume_url}`}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-xs font-medium text-zinc-300 hover:text-white transition-colors"
                >
                  Download / View
                </a>
              )}
            </div>
          </div>
        </section>

        {/* Basic Personal Details */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold text-white">Basic Information</h2>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                First name
              </label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Last name
              </label>
              <input
                type="text"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-4">
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Professional Headline
            </label>
            <input
              type="text"
              value={headline}
              onChange={(e) => setHeadline(e.target.value)}
              placeholder="e.g. Senior Full-Stack Engineer | Python, React & Distributed Systems"
              className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
            />
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Location
              </label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. San Francisco, CA or Remote"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Phone Number
              </label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+1 (555) 000-0000"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Total Years of Experience
              </label>
              <input
                type="number"
                step="0.5"
                min="0"
                value={yearsOfExp}
                onChange={(e) => setYearsOfExp(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="e.g. 4.5"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="mt-4">
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Professional Summary / Bio
            </label>
            <textarea
              rows={3}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="Tell employers and the recommendation engine about your background and goals..."
              className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
            />
          </div>
        </section>

        {/* Skills Taxonomy Tagger */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Skills & Proficiencies</h2>
              <p className="mt-1 text-xs text-zinc-400">
                Directly matches against employer job requirements in the recommendation system.
              </p>
            </div>
            <span className="text-xs font-medium text-teal-400">
              {skills.length} skills tagged
            </span>
          </div>

          {/* Autocomplete Input */}
          <div className="relative mt-4">
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
                placeholder="Search skills (e.g. Python, React, Docker, Machine Learning)..."
                className="block flex-1 rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => handleAddSkill(skillSearch)}
                className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-700 transition-colors"
              >
                Add Skill
              </button>
            </div>

            {/* Dropdown Suggestions */}
            {suggestedSkills.length > 0 && (
              <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-900 shadow-xl">
                {suggestedSkills.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => handleAddSkill(s.name, s.category)}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-zinc-200 hover:bg-teal-500/20 hover:text-white"
                  >
                    <span>{s.name}</span>
                    <span className="text-xs text-zinc-500 uppercase">{s.category}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tagged Skills List */}
          <div className="mt-4 space-y-2">
            {skills.map((skill, index) => (
              <div
                key={index}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-zinc-800/80 bg-zinc-950/50 p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-white">{skill.skill_name}</span>
                  {skill.category && (
                    <span className="rounded bg-zinc-800 px-2 py-0.5 text-[10px] uppercase text-zinc-400">
                      {skill.category}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  <select
                    value={skill.proficiency_level || "intermediate"}
                    onChange={(e) =>
                      handleUpdateSkill(index, "proficiency_level", e.target.value)
                    }
                    className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:outline-none"
                  >
                    <option value="beginner">Beginner</option>
                    <option value="intermediate">Intermediate</option>
                    <option value="advanced">Advanced</option>
                    <option value="expert">Expert</option>
                  </select>

                  <div className="flex items-center gap-1 text-xs text-zinc-400">
                    <input
                      type="number"
                      min="0"
                      max="30"
                      value={skill.years_of_experience ?? 2}
                      onChange={(e) =>
                        handleUpdateSkill(index, "years_of_experience", Number(e.target.value))
                      }
                      className="w-12 rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-xs text-zinc-200 text-center focus:outline-none"
                    />
                    <span>yrs</span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRemoveSkill(index)}
                    className="p-1 text-zinc-500 hover:text-rose-400 transition-colors"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Work Experience */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Briefcase className="h-5 w-5 text-teal-400" />
              Work Experience
            </h2>
            <button
              type="button"
              onClick={handleAddExperience}
              className="inline-flex items-center gap-1 rounded bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-700"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Position
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {experience.map((exp, idx) => (
              <div key={idx} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-semibold text-zinc-400">Role #{idx + 1}</span>
                  <button
                    type="button"
                    onClick={() => setExperience(experience.filter((_, i) => i !== idx))}
                    className="text-zinc-500 hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input
                    type="text"
                    placeholder="Job Title"
                    value={exp.title}
                    onChange={(e) => {
                      const copy = [...experience];
                      copy[idx].title = e.target.value;
                      setExperience(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                  <input
                    type="text"
                    placeholder="Company"
                    value={exp.company}
                    onChange={(e) => {
                      const copy = [...experience];
                      copy[idx].company = e.target.value;
                      setExperience(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input
                    type="text"
                    placeholder="Start Date (e.g. 2021-06)"
                    value={exp.start_date || ""}
                    onChange={(e) => {
                      const copy = [...experience];
                      copy[idx].start_date = e.target.value;
                      setExperience(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                  <input
                    type="text"
                    placeholder="End Date (or 'Present')"
                    value={exp.end_date || ""}
                    onChange={(e) => {
                      const copy = [...experience];
                      copy[idx].end_date = e.target.value;
                      setExperience(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                </div>
                <textarea
                  rows={2}
                  placeholder="Key responsibilities and achievements..."
                  value={exp.description || ""}
                  onChange={(e) => {
                    const copy = [...experience];
                    copy[idx].description = e.target.value;
                    setExperience(copy);
                  }}
                  className="w-full rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                />
              </div>
            ))}
          </div>
        </section>

        {/* Education */}
        <section className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6 backdrop-blur">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <GraduationCap className="h-5 w-5 text-teal-400" />
              Education
            </h2>
            <button
              type="button"
              onClick={handleAddEducation}
              className="inline-flex items-center gap-1 rounded bg-zinc-800 px-2.5 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-700"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Education
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {education.map((edu, idx) => (
              <div key={idx} className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-semibold text-zinc-400">Education #{idx + 1}</span>
                  <button
                    type="button"
                    onClick={() => setEducation(education.filter((_, i) => i !== idx))}
                    className="text-zinc-500 hover:text-rose-400"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input
                    type="text"
                    placeholder="Degree (e.g. B.S. in Computer Science)"
                    value={edu.degree}
                    onChange={(e) => {
                      const copy = [...education];
                      copy[idx].degree = e.target.value;
                      setEducation(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                  <input
                    type="text"
                    placeholder="Institution (e.g. Stanford University)"
                    value={edu.institution}
                    onChange={(e) => {
                      const copy = [...education];
                      copy[idx].institution = e.target.value;
                      setEducation(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input
                    type="number"
                    placeholder="Start Year"
                    value={edu.start_year || ""}
                    onChange={(e) => {
                      const copy = [...education];
                      copy[idx].start_year = e.target.value ? Number(e.target.value) : null;
                      setEducation(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                  <input
                    type="number"
                    placeholder="Graduation Year"
                    value={edu.end_year || ""}
                    onChange={(e) => {
                      const copy = [...education];
                      copy[idx].end_year = e.target.value ? Number(e.target.value) : null;
                      setEducation(copy);
                    }}
                    className="rounded border border-zinc-800 bg-zinc-900 p-2 text-sm text-zinc-200 focus:outline-none"
                  />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Bottom Save Action */}
        <div className="flex justify-end pt-4">
          <button
            type="submit"
            disabled={isSaving}
            className="inline-flex items-center gap-2 rounded-lg bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-md shadow-teal-500/20 hover:bg-teal-400 disabled:opacity-50 active:scale-[0.98] transition-all"
          >
            {isSaving ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-950 border-t-transparent" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save All Changes
          </button>
        </div>
      </form>
    </div>
  );
}
