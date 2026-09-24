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
  /** Canonical job-family name (plan §5). */
  family?: string | null;
  /** §14 "Powered by: <project> — <band>" (only surfaced at Moderate+). */
  project_relevance?: string | null;
}

export interface JobListResponse {
  items: JobDetail[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/** §12 explanation contract — components verbatim from the deterministic scorer. */
export interface ExplanationContract {
  summary: string;
  components: Record<string, number>;
  contributions: Record<string, number>;
  strengths?: string[];
  concerns?: string[];
  recommended_action?: string;
  /** Phase 3 rerank note (e.g. ranklet delta), never a score itself. */
  delta_note?: string | null;
}

export interface RecommendationItem {
  job: JobDetail;
  match_score: number;
  skill_match_score: number;
  content_similarity_score: number;
  matched_skills: string[];
  missing_skills: string[];
  match_reasons: string[];
  explanation?: ExplanationContract | null;
  readiness?: Readiness | null;
  family?: string | null;
  /** Ranking strategy that produced this item (deterministic | ltr_blend | ltr_full). */
  strategy?: string;
  /** Learned model version when the strategy used one (e.g. "ranklet v1"). */
  model_version?: string | null;
  /** Exploration propensity for this slot (1.0 = always shown; logged for IPS). */
  propensity?: number | null;
}

export interface RecommendationFeedResponse {
  items: RecommendationItem[];
  total: number;
  profile_completeness_score: number;
  recommendation_type: "content_based" | "cold_start";
  recommendation_strategy: string;
  /** Phase 3: actual rerank strategy + model version behind this feed. */
  strategy?: string;
  model_version?: string | null;
  /** Set when the feed includes an exploratory slot (propensity logged). */
  personalization_note?: string | null;
}

export type ApplicationStatus =
  | "applied"
  | "viewed"
  | "shortlisted"
  | "interview"
  | "rejected"
  | "offer"
  | "saved";

export interface ApplicationStats {
  total_applied: number;
  applied: number;
  viewed: number;
  shortlisted: number;
  interview: number;
  rejected: number;
  offer: number;
  /** Phase 4: saved-later count (plan §19 /saved). */
  saved?: number;
  /** Phase 4: required skills across successful applications (§18). */
  successful_skills?: string[];
  /** Phase 4: "… a historical observation, not a causal claim." (§18). */
  observation_note?: string;
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

// ---------------- Phase 4: Feedback · Preferences · NL · Resume · Projects ---------------- //

export type FeedbackReason =
  | "relevant"
  | "not_relevant"
  | "already_applied"
  | "not_interested"
  | "too_difficult"
  | "location_issue"
  | "salary_issue"
  | "other";

export interface FeedbackPayload {
  job_id: string;
  reason: FeedbackReason;
  note?: string;
}

export interface FeedbackResponse {
  id: string;
  job_id: string;
  reason: FeedbackReason;
  note?: string | null;
  created_at?: string | null;
  /** What the M4 update did to your weights (never a score itself). */
  personalization_note?: string | null;
}

/** One bar in Settings → "Your preferences" (§16). */
export interface WeightBar {
  component: string;
  label: string;
  weight: number;
  global_weight: number;
}

export interface WeightHistoryEntry {
  component: string;
  delta: number;
  weight: number;
  reason: string;
  at: string;
}

export interface AffinityEntry {
  skill: string;
  score: number;
}

export interface PreferenceState {
  weights: WeightBar[];
  n_events: number;
  shrinkage: number;
  updated_at?: string | null;
  history: WeightHistoryEntry[];
  affinities: AffinityEntry[];
  personalization_note?: string | null;
}

/** §17 NL search response — parsed filters are echoed as editable chips. */
export interface JobNlResponse {
  items: JobDetail[];
  total: number;
  mode: "llm" | "fts";
  parsed_filters: Record<string, unknown>;
  q: string;
}

export interface AtsCheck {
  name: string;
  status: "PASS" | "WARN" | "FAIL";
  detail: string;
}

export interface ResumeOptimizeResponse {
  job_id: string;
  job_title: string;
  ats: {
    checks: AtsCheck[];
    ats_score: number;
    missing_keywords: string[];
    weak_evidence: string[];
    keyword_coverage: number;
    quantified_bullet_pct: number;
    bullet_count: number;
  };
  suggestions: {
    bullet: string;
    issues: string[];
    rewrite: string;
    status: string;
  }[];
  violations_dropped: number;
  llm_used: boolean;
  disclaimer: string;
}

export type ProjectBand = "Very high" | "High" | "Moderate" | "Low";

export interface ProjectMapItem {
  project_id: string | null;
  title: string;
  score: number;
  band: ProjectBand;
  matched_skills: string[];
}

export interface ProjectMapResponse {
  job_id: string;
  job_title: string;
  items: ProjectMapItem[];
  best?: ProjectMapItem | null;
  powered_by?: string | null;
}

export interface FamilyBenefit {
  family: string;
  score: number;
  band: ProjectBand;
}

export interface ProjectBenefitItem {
  project_id: string;
  title: string;
  benefits: FamilyBenefit[];
}

export interface ProjectBenefitsResponse {
  items: ProjectBenefitItem[];
}

// ---------------- Phase 5: Admin · M5 Onboarding ---------------- //

export interface AdminSkillItem {
  id: string;
  name: string;
  category?: string | null;
  profiles: number;
  jobs: number;
  aliases: number;
  has_embedding: boolean;
}

export interface AdminSkillsResponse {
  total_skills: number;
  items: AdminSkillItem[];
}

export interface MergeCount {
  moved: number;
  deduped?: number;
  dropped?: number;
  skipped?: number;
}

export interface MergeReport {
  status: string;
  source: { id: string; name: string };
  target: { id: string; name: string };
  profile_skills: MergeCount;
  job_skills: MergeCount;
  skill_aliases: MergeCount;
  skill_edges: MergeCount;
  skill_affinities: MergeCount;
  embedding_refreshed: boolean;
}

export interface DuplicateJobRef {
  id: string;
  title: string;
  location?: string | null;
  skills: number;
}

export interface DuplicatePair {
  cosine: number;
  title_similarity: number;
  job_a: DuplicateJobRef;
  job_b: DuplicateJobRef;
  suggested_survivor_id: string;
  suggested_retire_id: string;
}

export interface DuplicatesResponse {
  threshold: number;
  title_similarity_min: number;
  jobs_examined: number;
  pairs: DuplicatePair[];
}

export interface LlmUsageTotals {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  cache_hits: number;
  flagged: number;
  avg_latency_ms: number;
  estimated_cost_usd: number | null;
}

export interface LlmUsageResponse {
  totals: LlmUsageTotals;
  by_route: {
    route: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    avg_latency_ms: number;
    flagged: number;
  }[];
  by_model: {
    provider: string;
    model: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost_usd: number | null;
  }[];
  recent: {
    id: string;
    route: string;
    provider: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    latency_ms: number;
    cached: boolean;
    flagged: boolean;
    created_at: string | null;
  }[];
  llm_enabled: boolean;
}

export interface ParseFailureItem {
  id: string;
  profile_id: string;
  original_filename?: string | null;
  parse_status: string;
  parser_used?: string | null;
  stuck: boolean;
  created_at: string | null;
}

export interface ParseFailuresResponse {
  items: ParseFailureItem[];
  stuck_after_minutes: number;
}

export interface AdminWeightBar {
  component: string;
  label: string;
  weight: number;
  default: number;
}

export interface AdminConfigResponse {
  weights: AdminWeightBar[];
  source: "system_config" | "defaults";
  sum: number;
  llm: {
    enabled: boolean;
    provider: string;
    model: string;
    has_api_key: boolean;
    kill_switch: string;
  };
  m4: { learning_rate: number; bounds: number[]; shrinkage_k: number };
}

export interface ConfigSaveResponse {
  status: string;
  source: string;
  weights: Record<string, number>;
  sum: number;
}

export interface ModelRegistryItem {
  id: string;
  name: string;
  version: string;
  artifact_path: string;
  artifact_exists: boolean;
  metrics: Record<string, unknown>;
  active: boolean;
  trained_at: string | null;
}

export interface OnboardingPairOption {
  label: string;
  blurb: string;
  shape: Record<string, number>;
}

export interface OnboardingPair {
  index: number;
  question: string;
  a: OnboardingPairOption;
  b: OnboardingPairOption;
}

export interface OnboardingPairsResponse {
  pairs: OnboardingPair[];
  components: { component: string; label: string }[];
  note: string;
}

export interface OnboardingCompletePayload {
  choices: { pair_index: number; chosen: "a" | "b" }[];
  target_family?: string;
}

export interface OnboardingCompleteResponse {
  weights: { component: string; label: string; weight: number }[];
  target_family: string | null;
  message: string;
}
