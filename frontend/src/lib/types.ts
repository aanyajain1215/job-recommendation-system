export type UserRole = "job_seeker" | "employer" | "admin";
export type EmploymentType = "full_time" | "part_time" | "contract" | "internship" | "temporary";
export type ExperienceLevel = "entry" | "mid" | "senior" | "lead" | "executive";
export type JobStatus = "draft" | "published" | "closed" | "archived";
export type ProficiencyLevel = "beginner" | "intermediate" | "advanced" | "expert";

export interface Skill {
  id: string;
  name: string;
  category?: string | null;
}

export interface ProfileSkillItem {
  skill_name: string;
  category?: string | null;
  proficiency_level?: ProficiencyLevel | null;
  years_of_experience?: number | null;
}

export interface EducationItem {
  degree: string;
  institution: string;
  field_of_study?: string | null;
  start_year?: number | null;
  end_year?: number | null;
}

export interface ExperienceItem {
  title: string;
  company: string;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  current?: boolean;
  description?: string | null;
}

export interface ProfileDetail {
  id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  headline?: string | null;
  bio?: string | null;
  location?: string | null;
  phone?: string | null;
  resume_url?: string | null;
  raw_resume_text?: string | null;
  parsed_resume_data?: Record<string, unknown> | null;
  years_of_experience?: number | null;
  education?: EducationItem[] | null;
  work_experience?: ExperienceItem[] | null;
  skills: ProfileSkillItem[];
  created_at: string;
  updated_at: string;
}

export interface ProfileUpdatePayload {
  first_name?: string;
  last_name?: string;
  headline?: string | null;
  bio?: string | null;
  location?: string | null;
  phone?: string | null;
  years_of_experience?: number | null;
  skills?: ProfileSkillItem[];
  education?: EducationItem[];
  work_experience?: ExperienceItem[];
}

export interface CompanySummary {
  id: string;
  name: string;
  slug: string;
  location?: string | null;
  website?: string | null;
  is_verified: boolean;
}

export interface ProfileSummary {
  id: string;
  first_name: string;
  last_name: string;
  headline?: string | null;
  location?: string | null;
  resume_url?: string | null;
  years_of_experience?: number | null;
}

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  profile?: ProfileSummary | null;
  companies: CompanySummary[];
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AuthResponse extends AuthTokens {
  user: User;
}

export interface RegisterPayload {
  email: string;
  password: string;
  role: "job_seeker" | "employer";
  first_name?: string;
  last_name?: string;
  company_name?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface JobSkillRequirement {
  skill_name: string;
  category?: string | null;
  is_required: boolean;
  importance_weight: number;
}

export interface JobSkillInput {
  skill_name: string;
  is_required?: boolean;
  importance_weight?: number;
}

export interface JobCreatePayload {
  company_id?: string;
  title: string;
  description: string;
  requirements?: string;
  employment_type: EmploymentType;
  experience_level: ExperienceLevel;
  location: string;
  is_remote: boolean;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string;
  skills?: JobSkillInput[];
}

export interface JobDetail {
  id: string;
  company_id: string;
  posted_by_user_id: string;
  title: string;
  description: string;
  requirements?: string | null;
  employment_type: EmploymentType;
  experience_level: ExperienceLevel;
  location: string;
  is_remote: boolean;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  company: CompanySummary;
  skills: JobSkillRequirement[];
  applicant_count: number;
  relevance_score?: number | null;
  snippet?: string | null;
}

export interface JobListResponse {
  items: JobDetail[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface RecommendationItem {
  job: JobDetail;
  match_score: number;
  skill_match_score: number;
  content_similarity_score: number;
  matched_skills: string[];
  missing_skills: string[];
  match_reasons: string[];
}

export interface RecommendationFeedResponse {
  items: RecommendationItem[];
  total: number;
  profile_completeness_score: number;
  recommendation_type: "content_based" | "cold_start";
  recommendation_strategy: string;
}

export type ApplicationStatus =
  | "applied"
  | "viewed"
  | "shortlisted"
  | "interview"
  | "rejected"
  | "offer";

export interface ApplicationStats {
  total_applied: number;
  applied: number;
  viewed: number;
  shortlisted: number;
  interview: number;
  rejected: number;
  offer: number;
}

export interface ApplicationItem {
  id: string;
  job_id: string;
  user_id: string;
  status: ApplicationStatus;
  cover_note?: string | null;
  resume_url_snapshot?: string | null;
  applied_at: string;
  created_at?: string;
  updated_at: string;
  job?: JobDetail | null;
}

// ---------------- Phase 2: Gap · Roadmap · Simulator · Careers ---------------- //

export type Readiness = { value: number; band: "low" | "medium" | "high" };

export type GapStatus = "STRONG" | "PARTIAL" | "TRANSFERABLE" | "MISSING";

export interface GapClassItem {
  skill: string;
  status: GapStatus;
  evidence: {
    reason?: string;
    proficiency?: string | null;
    years?: number | null;
    transfer_similarity?: number;
    via_skill?: string;
    [key: string]: unknown;
  };
}

export interface GapResponse {
  job_id: string;
  job_title: string;
  match_score: number;
  gap_score: number;
  readiness: Readiness;
  classes: GapClassItem[];
  counts: { strong: number; partial: number; transferable: number; missing: number };
  missing_required: string[];
  weakest_link: string | null;
  reasons: string[];
}

export interface RoadmapStep {
  seq: number;
  kind: "skill" | "project";
  title: string;
  skill: string | null;
  category: string | null;
  est_hours: number;
  rationale: Record<string, unknown>;
  /** Row UUID of the persisted CareerPathStep (null when no family anchor). */
  id?: string | null;
  /** Completion state persisted in the DB (never clobbered by re-reads). */
  done?: boolean;
}

export interface RoadmapPhase {
  label: string;
  est_hours: number;
  steps: RoadmapStep[];
}

export interface RoadmapResponse {
  id: string | null;
  job_id: string;
  job_title: string;
  steps: RoadmapStep[];
  phases: RoadmapPhase[];
  candidates: string[];
  effort_band: "low" | "medium" | "high";
  total_hours: number;
  readiness_before: Readiness;
  readiness_after: Readiness;
  summary: string;
}

export interface StepCompleteResponse {
  step_id: string;
  path_id: string;
  seq: number;
  done_at: string;
  path_status: string;
  steps_done: number;
  steps_total: number;
}

export interface SkillMutation {
  name: string;
  level?: ProficiencyLevel;
  years?: number | null;
}

export interface SimulateRequest {
  add_skills?: SkillMutation[];
  remove_skills?: string[];
  expected_salary?: { min?: number | null; max?: number | null; currency?: string | null } | null;
  location?: string | null;
  work_mode?: "remote" | "hybrid" | "onsite" | null;
  target_family?: string | null;
  add_project?: { name?: string; description?: string; skills?: string[] } | null;
  add_cert?: { name?: string; issuer?: string } | null;
  target_job_id?: string | null;
}

export interface SimulateDelta {
  job_id: string;
  job_title: string;
  before: number;
  after: number;
  delta: number;
  band_before: string;
  band_after: string;
  band_changed: boolean;
  newly_eligible: boolean;
  lost: boolean;
}

export interface SimulateTarget {
  job_id: string;
  job_title: string;
  before: number;
  after: number;
  delta: number;
  band_before: string;
  band_after: string;
  per_skill: { skill: string; score: number; band: string }[];
}

export interface ResultDelta {
  before: { mean_score: number; band_counts: Record<string, number> };
  after: { mean_score: number; band_counts: Record<string, number> };
  deltas: SimulateDelta[];
  target: SimulateTarget | null;
  mutation: Record<string, unknown>;
}

export interface SimulateResponse {
  id: string | null;
  mutation: Record<string, unknown>;
  result_delta: ResultDelta;
}

export interface SimulationListItem {
  id: string;
  mutation: Record<string, unknown>;
  result_delta: ResultDelta;
  created_at: string;
}

export interface SimulationListResponse {
  items: SimulationListItem[];
  total: number;
}

export interface FamilySuggestion {
  family_id: string;
  family: string;
  affinity: number;
  overlap: number;
  semantic: number;
  core_skill_count: number;
  matched_count: number;
  transfer_count: number;
  explanation: {
    top_skills: string[];
    transfer_count: number;
    nearest_edge: { from: string; to: string; relation: string } | null;
    note: string;
  };
}

export interface DiscoverResponse {
  threshold: number;
  target_family: string | null;
  suggestions: FamilySuggestion[];
  presets: FamilySuggestion[];
  explored: number;
}
