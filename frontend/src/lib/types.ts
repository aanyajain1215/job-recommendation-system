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
