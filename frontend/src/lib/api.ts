import {
  AdminConfigResponse,
  AdminSkillsResponse,
  ApplicationItem,
  ApplicationStats,
  ApplicationStatus,
  CompanyDetail,
  ConfigSaveResponse,
  DiscoverResponse,
  DuplicatesResponse,
  EmployerApplication,
  FeedbackPayload,
  FeedbackResponse,
  GapResponse,
  JobCreatePayload,
  JobDetail,
  JobListResponse,
  JobNlResponse,
  JobStatus,
  JobUpdatePayload,
  LlmUsageResponse,
  MergeReport,
  ModelRegistryItem,
  OnboardingCompletePayload,
  OnboardingCompleteResponse,
  OnboardingPairsResponse,
  OnboardingFlowResponse,
  OnboardingAnswer,
  ParseFailuresResponse,
  PostingInsights,
  PostingPerformance,
  PostingPipeline,
  PostingTalent,
  PreferenceState,
  ProfileDetail,
  ProfileUpdatePayload,
  ProjectBenefitsResponse,
  ProjectMapResponse,
  RecommendationFeedResponse,
  ResumeOptimizeResponse,
  RoadmapResponse,
  SimulateRequest,
  SimulateResponse,
  SimulationListResponse,
  Skill,
  StepCompleteResponse,
  WhatIfRequest,
  WhatIfResult,
} from "./types";

export type ReadinessResponse = {
  status: string;
  service: string;
  database: string;
  postgres_version: string;
  database_time: string;
  heartbeat_id: string;
  heartbeat_message: string;
  heartbeat_recorded_at: string;
};

export type HealthResult =
  | { ok: true; data: ReadinessResponse }
  | { ok: false; error: string };

export function getServerApiBaseUrl(): string {
  const url = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error("API_INTERNAL_URL or NEXT_PUBLIC_API_URL must be set");
  }
  return url.replace(/\/$/, "");
}

export function getBrowserApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error("NEXT_PUBLIC_API_URL must be set");
  }
  return url.replace(/\/$/, "");
}

export async function fetchReadiness(
  apiBaseUrl: string,
): Promise<HealthResult> {
  const url = `${apiBaseUrl}/api/v1/health/ready`;
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      const body = await response.text();
      return {
        ok: false,
        error: `API ${response.status} from ${url}: ${body}`,
      };
    }
    const data = (await response.json()) as ReadinessResponse;
    return { ok: true, data };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return { ok: false, error: `Failed to reach ${url}: ${message}` };
  }
}

// ---------------- Profiles API ---------------- //

export async function getMyProfile(token: string): Promise<ProfileDetail> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/profiles/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to fetch profile" }));
    throw new Error(err.detail || "Failed to fetch profile");
  }
  return res.json();
}

export async function updateMyProfile(
  payload: ProfileUpdatePayload,
  token: string,
): Promise<ProfileDetail> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/profiles/me`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to update profile" }));
    throw new Error(err.detail || "Failed to update profile");
  }
  return res.json();
}

export async function uploadResume(
  file: File,
  token: string,
): Promise<{ resume_url: string; filename: string }> {
  const base = getBrowserApiBaseUrl();
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${base}/api/v1/profiles/me/resume`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to upload resume" }));
    throw new Error(err.detail || "Failed to upload resume");
  }
  return res.json();
}

export async function reparseResume(token: string): Promise<{ status: string; message: string }> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/profiles/me/resume/reparse`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to re-parse resume" }));
    throw new Error(err.detail || "Failed to re-parse resume");
  }
  return res.json();
}

// ---------------- Skills Taxonomy API ---------------- //

export async function getSkills(search?: string, category?: string): Promise<Skill[]> {
  const base = getBrowserApiBaseUrl();
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  params.set("limit", "50");

  const res = await fetch(`${base}/api/v1/skills?${params.toString()}`);
  if (!res.ok) return [];
  return res.json();
}

// ---------------- Jobs API ---------------- //

export async function createJob(
  payload: JobCreatePayload,
  token: string,
): Promise<JobDetail> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create job" }));
    throw new Error(err.detail || "Failed to create job posting");
  }
  return res.json();
}

export async function getJobs(filters?: {
  q?: string;
  search?: string;
  sort_by?: "relevance" | "date" | "salary";
  location?: string;
  is_remote?: boolean;
  employment_type?: string;
  experience_level?: string;
  skill?: string;
  min_salary?: number;
  page?: number;
}): Promise<JobListResponse> {
  const base = getBrowserApiBaseUrl();
  const params = new URLSearchParams();
  if (filters?.q) params.set("q", filters.q);
  if (filters?.search) params.set("search", filters.search);
  if (filters?.sort_by) params.set("sort_by", filters.sort_by);
  if (filters?.location) params.set("location", filters.location);
  if (filters?.is_remote !== undefined) params.set("is_remote", String(filters.is_remote));
  if (filters?.employment_type) params.set("employment_type", filters.employment_type);
  if (filters?.experience_level) params.set("experience_level", filters.experience_level);
  if (filters?.skill) params.set("skill", filters.skill);
  if (filters?.min_salary) params.set("min_salary", String(filters.min_salary));
  if (filters?.page) params.set("page", String(filters.page));

  const res = await fetch(`${base}/api/v1/jobs?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to fetch jobs");
  }
  return res.json();
}

export async function getJobDetail(jobId: string): Promise<JobDetail> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to fetch job details");
  }
  return res.json();
}

export async function getEmployerJobs(token: string): Promise<JobDetail[]> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/employer/jobs`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error("Failed to fetch employer jobs");
  }
  return res.json();
}

export async function deleteJob(jobId: string, token: string): Promise<void> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/jobs/${jobId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error("Failed to delete job");
  }
}

// ---------------- Employer API (E0: company + posting lifecycle) ---------------- //

export async function getMyCompany(token: string): Promise<CompanyDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/company`, token);
}

/** For employers who registered without a company — 409 if one exists. */
export async function createMyCompany(payload: { name: string }, token: string): Promise<CompanyDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/company`, token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Partial update — omitted fields stay unchanged; "" clears an optional field. */
export async function updateMyCompany(
  payload: Partial<Omit<CompanyDetail, "id" | "slug" | "is_verified" | "open_postings">>,
  token: string,
): Promise<CompanyDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/company`, token, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function setPostingStatus(
  jobId: string,
  next: JobStatus,
  token: string,
): Promise<JobDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/status`, token, {
    method: "PATCH",
    body: JSON.stringify({ status: next }),
  });
}

/** Clone a posting; the clone is created as a DRAFT. */
export async function duplicatePosting(jobId: string, token: string): Promise<JobDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/duplicate`, token, {
    method: "POST",
  });
}

/** Content edit for an existing posting (lifecycle goes via setPostingStatus). */
export async function updateJob(
  jobId: string,
  payload: JobUpdatePayload,
  token: string,
): Promise<JobDetail> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/jobs/${jobId}`, token, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

// ---------------- Employer API (E1: applicant pipeline) ---------------- //

/** Funnel aggregates for one posting (rows come from getJobApplicants). */
export async function getPostingPipeline(jobId: string, token: string): Promise<PostingPipeline> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/pipeline`, token);
}

/** All applicant rows for one posting, newest first. */
export async function getJobApplicants(jobId: string, token: string): Promise<EmployerApplication[]> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/jobs/${jobId}/applications`, token);
}

/** Move one applicant to a different pipeline stage. */
export async function setApplicationStatus(
  applicationId: string,
  next: ApplicationStatus,
  token: string,
): Promise<EmployerApplication> {
  return authedJson(
    `${getBrowserApiBaseUrl()}/api/v1/employer/applications/${applicationId}/status`,
    token,
    {
      method: "PATCH",
      body: JSON.stringify({ status: next }),
    },
  );
}

// ---------------- Employer API (E2: reverse talent match) ---------------- //

/**
 * Reverse-match ranking of this posting's OWN applicants (the global seeker
 * pool is never exposed to employers).
 */
export async function getPostingTalent(jobId: string, token: string): Promise<PostingTalent> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/talent`, token);
}

// ---------------- Employer API (E3: insights) ---------------- //

/** JD health, salary benchmark and supply/demand gaps for one posting. */
export async function getPostingInsights(jobId: string, token: string): Promise<PostingInsights> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/insights`, token);
}

// ---------------- Employer API (E4: performance) ---------------- //

/** 30-day application series, stage conversion and health for one posting. */
export async function getPostingPerformance(
  jobId: string,
  token: string,
): Promise<PostingPerformance> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/performance`, token);
}

// ---------------- Employer API (E5: what-if relaxer) ---------------- //

/**
 * Simulate relaxing a posting's constraints. Never modifies the posting —
 * apply the result explicitly with updateJob.
 */
export async function simulateWhatIf(
  jobId: string,
  payload: WhatIfRequest,
  token: string,
): Promise<WhatIfResult> {
  return authedJson(`${getBrowserApiBaseUrl()}/api/v1/employer/postings/${jobId}/whatif`, token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------- Recommendations API ---------------- //

export async function getRecommendations(
  token: string,
  limit: number = 20,
): Promise<RecommendationFeedResponse> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/recommendations?limit=${limit}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to fetch recommendations" }));
    throw new Error(err.detail || "Failed to fetch recommendations");
  }
  return res.json();
}

// ---------------- Applications API ---------------- //

export async function applyToJob(
  jobId: string,
  token: string,
  coverNote?: string,
): Promise<ApplicationItem> {
  return api.post<ApplicationItem>(
    `/jobs/${jobId}/apply`,
    { job_id: jobId, cover_note: coverNote || undefined },
    { Authorization: `Bearer ${token}` },
  );
}

export async function getMyApplications(token: string): Promise<ApplicationItem[]> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/applications/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return [];
  return res.json();
}

export async function getMyApplicationStats(token: string): Promise<ApplicationStats> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/applications/me/stats`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    return {
      total_applied: 0,
      applied: 0,
      viewed: 0,
      shortlisted: 0,
      interview: 0,
      rejected: 0,
      offer: 0,
      saved: 0,
      successful_skills: [],
      observation_note: "",
    };
  }
  return res.json();
}

// ---------------- Phase 2: Gap / Roadmap / Simulator / Careers ---------------- //

async function authedJson<T>(url: string, token: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `Request failed (${res.status})` }));
    throw new Error(
      typeof err.detail === "string" ? err.detail : `Request failed (${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

export async function getJobGap(jobId: string, token: string): Promise<GapResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/recommendations/${jobId}/gap`, token);
}

export async function getJobRoadmap(jobId: string, token: string): Promise<RoadmapResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/recommendations/${jobId}/roadmap`, token);
}

export async function completeRoadmapStep(
  pathId: string,
  stepId: string,
  token: string,
): Promise<StepCompleteResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/roadmaps/${pathId}/steps/${stepId}/complete`, token, {
    method: "POST",
  });
}

export async function runSimulation(
  payload: SimulateRequest,
  token: string,
): Promise<SimulateResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/simulate`, token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getSimulations(
  token: string,
  limit: number = 10,
): Promise<SimulationListResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/simulations?limit=${limit}`, token);
}

export async function discoverCareers(token: string): Promise<DiscoverResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/careers/discover`, token);
}

// ---------------- Phase 4: Feedback · Preferences · NL · Resume · Projects · Tracker ---------------- //

export async function submitFeedback(
  payload: FeedbackPayload,
  token: string,
): Promise<FeedbackResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/feedback`, token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getPreferences(token: string): Promise<PreferenceState> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/preferences`, token);
}

export async function resetPreferences(token: string): Promise<PreferenceState> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/preferences`, token, {
    method: "PATCH",
    body: JSON.stringify({ reset: true }),
  });
}

export async function searchJobsNL(q: string): Promise<JobNlResponse> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/jobs/nl?q=${encodeURIComponent(q)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error("Natural-language search failed");
  }
  return res.json();
}

export async function optimizeResume(
  jobId: string,
  token: string,
): Promise<ResumeOptimizeResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/jobs/${jobId}/resume-optimize`, token, {
    method: "POST",
  });
}

export async function getProjectMap(
  jobId: string,
  token: string,
): Promise<ProjectMapResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/jobs/${jobId}/project-map`, token);
}

export async function getProjectBenefits(
  token: string,
): Promise<ProjectBenefitsResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/profiles/me/project-benefits`, token);
}

export async function saveJob(jobId: string, token: string): Promise<ApplicationItem> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/jobs/${jobId}/save`, token, {
    method: "POST",
  });
}

export async function updateApplication(
  applicationId: string,
  status: ApplicationStatus,
  token: string,
): Promise<ApplicationItem> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/applications/${applicationId}`, token, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function removeSavedJob(
  applicationId: string,
  token: string,
): Promise<{ status: string; id: string }> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/applications/${applicationId}`, token, {
    method: "DELETE",
  });
}

// ---------------- Phase 5: Admin · M5 Onboarding ---------------- //

export async function getAdminSkills(token: string, q?: string): Promise<AdminSkillsResponse> {
  const base = getBrowserApiBaseUrl();
  const suffix = q ? `?q=${encodeURIComponent(q)}` : "";
  return authedJson(`${base}/api/v1/admin/skills${suffix}`, token);
}

export async function mergeSkills(
  sourceId: string,
  targetId: string,
  token: string,
): Promise<MergeReport> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/skills/merge`, token, {
    method: "POST",
    body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
  });
}

export async function getJobDuplicates(token: string): Promise<DuplicatesResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/jobs/duplicates`, token);
}

export async function getLlmUsage(token: string): Promise<LlmUsageResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/llm-usage`, token);
}

export async function getParseFailures(token: string): Promise<ParseFailuresResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/parse-failures`, token);
}

export async function retryParse(
  resumeId: string,
  token: string,
): Promise<{ status: string; resume_id: string }> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/parse-failures/${resumeId}/retry`, token, {
    method: "POST",
  });
}

export async function getAdminConfig(token: string): Promise<AdminConfigResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/config`, token);
}

export async function putAdminConfig(
  weights: Record<string, number>,
  token: string,
): Promise<ConfigSaveResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/config`, token, {
    method: "PUT",
    body: JSON.stringify({ weights }),
  });
}

export async function getAdminModels(token: string): Promise<{
  items: ModelRegistryItem[];
  total: number;
}> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/admin/models`, token);
}

export async function getOnboardingPairs(): Promise<OnboardingPairsResponse> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/onboarding/pairs`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load onboarding questions");
  return res.json();
}

// ---------------- Adaptive onboarding ---------------- //

export async function getOnboardingFlow(): Promise<OnboardingFlowResponse> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/onboarding/flow`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to start the onboarding flow");
  return res.json();
}

export async function nextOnboardingQuestion(
  answers: OnboardingAnswer[],
): Promise<OnboardingFlowResponse> {
  const base = getBrowserApiBaseUrl();
  const res = await fetch(`${base}/api/v1/onboarding/next`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to get the next question");
  return res.json();
}

export async function completeOnboarding(
  payload: OnboardingCompletePayload,
  token: string,
): Promise<OnboardingCompleteResponse> {
  const base = getBrowserApiBaseUrl();
  return authedJson(`${base}/api/v1/onboarding/complete`, token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------- Generic API Client (Supports TanStack Query & direct use) ---------------- //

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

/**
 * Single source of truth for the localStorage auth keys.
 *
 * auth-context writes them on login/register; `api.request()` reads the
 * access token to attach `Authorization`. (Both used to diverge — the
 * request helper looked up `jobrec_token`, so authenticated `api.*` calls
 * silently sent no token and the backend answered 401 "Not authenticated".)
 */
export const ACCESS_TOKEN_KEY = "jobrec_access_token";
export const REFRESH_TOKEN_KEY = "jobrec_refresh_token";

export const api = {
  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const base = getBrowserApiBaseUrl();
    const cleanEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
    const path = cleanEndpoint.startsWith("/api/v1") ? cleanEndpoint : `/api/v1${cleanEndpoint}`;
    const url = `${base}${path}`;

    const headers = new Headers(options.headers || {});
    if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    if (!headers.has("Authorization") && typeof window !== "undefined") {
      const token = localStorage.getItem(ACCESS_TOKEN_KEY);
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
    }

    const res = await fetch(url, {
      ...options,
      headers,
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      throw new ApiError(errData.detail || "API request failed", res.status, errData);
    }

    return res.json();
  },

  get<T>(endpoint: string, headers?: HeadersInit) {
    return this.request<T>(endpoint, { method: "GET", headers });
  },

  post<T>(endpoint: string, body?: unknown, headers?: HeadersInit) {
    return this.request<T>(endpoint, {
      method: "POST",
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  patch<T>(endpoint: string, body?: unknown, headers?: HeadersInit) {
    return this.request<T>(endpoint, {
      method: "PATCH",
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  delete<T>(endpoint: string, headers?: HeadersInit) {
    return this.request<T>(endpoint, { method: "DELETE", headers });
  },
};
