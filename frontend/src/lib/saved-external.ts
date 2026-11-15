import { JobDetail } from "./types";

export interface ExternalSavedJob {
  saved_id: string; // local id
  job: JobDetail;
  saved_at: string; // ISO
}

const KEY_PREFIX = "jobrec_saved_external_jobs_v1";

function keyFor(userId?: string | null) {
  return `${KEY_PREFIX}:${userId || "anon"}`;
}

export function listExternalSavedJobs(userId?: string | null): ExternalSavedJob[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(keyFor(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as ExternalSavedJob[];
  } catch {
    return [];
  }
}

function write(userId: string | null | undefined, items: ExternalSavedJob[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(keyFor(userId), JSON.stringify(items));
}

export function isExternalJobSaved(jobId: string, userId?: string | null): boolean {
  return listExternalSavedJobs(userId).some((x) => x.job?.id === jobId);
}

export function saveExternalJob(job: JobDetail, userId?: string | null): ExternalSavedJob {
  const items = listExternalSavedJobs(userId);
  const existing = items.find((x) => x.job?.id === job.id);
  if (existing) return existing;
  const entry: ExternalSavedJob = {
    saved_id: `ext_${job.id}`,
    job,
    saved_at: new Date().toISOString(),
  };
  const next = [entry, ...items];
  write(userId, next);
  return entry;
}

export function removeExternalSavedJob(jobId: string, userId?: string | null): void {
  const items = listExternalSavedJobs(userId).filter((x) => x.job?.id !== jobId);
  write(userId, items);
}
