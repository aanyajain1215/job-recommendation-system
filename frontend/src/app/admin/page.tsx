"use client";

import { useCallback, useEffect, useState, type ComponentType, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import {
  createAdminFlag,
  getAdminConfig,
  getAdminEmployers,
  getAdminFlags,
  getAdminModels,
  getAdminOverview,
  getAdminSkills,
  getAdminUsers,
  getJobDuplicates,
  getLlmUsage,
  getParseFailures,
  getSuspiciousEmployers,
  getSuspiciousJobs,
  mergeSkills,
  putAdminConfig,
  retryParse,
  updateAdminEmployer,
  updateAdminFlag,
  updateAdminJobStatus,
  updateAdminUser,
} from "@/lib/api";
import {
  AdminConfigResponse,
  AdminEmployerItem,
  AdminEmployersResponse,
  AdminFlagItem,
  AdminFlagsResponse,
  AdminOverview,
  AdminSkillsResponse,
  AdminSuspiciousJobsResponse,
  AdminUserItem,
  AdminUsersResponse,
  DuplicatesResponse,
  FlagSeverity,
  FlagStatus,
  FlagTargetType,
  LlmUsageResponse,
  MergeReport,
  ModelRegistryItem,
  ParseFailuresResponse,
  UserRole,
} from "@/lib/types";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BadgeCheck,
  Ban,
  Building2,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Database,
  ExternalLink,
  Flag,
  GitMerge,
  LayoutDashboard,
  Loader2,
  Radio,
  RefreshCw,
  Save,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Trophy,
  Users,
  UserX,
  Wrench,
  X,
  Zap,
} from "lucide-react";

const TABS = [
  { id: "pulse", label: "Pulse", icon: LayoutDashboard },
  { id: "users", label: "Users", icon: Users },
  { id: "employers", label: "Employers", icon: Building2 },
  { id: "moderation", label: "Moderation", icon: ShieldAlert },
  { id: "ops", label: "AI & Ops", icon: Activity },
  { id: "config", label: "Weights & Models", icon: SlidersHorizontal },
] as const;

type TabId = (typeof TABS)[number]["id"];

const ROLE_OPTIONS: UserRole[] = ["job_seeker", "employer", "admin"];
const ROLE_LABELS: Record<UserRole, string> = {
  job_seeker: "Job seeker",
  employer: "Employer",
  admin: "Admin",
};

const SEVERITY_STYLES: Record<FlagSeverity, string> = {
  low: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30",
  medium: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  high: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};

const FLAG_STATUS_STYLES: Record<FlagStatus, string> = {
  open: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  resolved: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  dismissed: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30",
};

const TARGET_LABELS: Record<FlagTargetType, string> = {
  job: "Job posting",
  company: "Employer",
  user: "Account",
};

function fmt(value: number): string {
  return value.toLocaleString("en-US");
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function relativeTime(value?: string | null): string {
  if (!value) return "never";
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return "—";
  const minutes = Math.round((Date.now() - time) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(value);
}

function errMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function riskTone(score: number): string {
  if (score >= 8) return "bg-rose-500/10 text-rose-300 ring-rose-500/30";
  if (score >= 5) return "bg-amber-500/10 text-amber-300 ring-amber-500/30";
  return "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30";
}

function StatCard({
  label,
  value,
  detail,
  icon: Icon,
  accent,
  live = false,
}: {
  label: string;
  value: string;
  detail: string;
  icon: ComponentType<{ className?: string }>;
  accent: string;
  live?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {live && (
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </span>
          )}
          {label}
        </p>
        <Icon className={`h-4 w-4 ${accent}`} />
      </div>
      <p className="mt-2 text-2xl font-bold tracking-tight text-zinc-100">{value}</p>
      <p className="mt-1 text-[11px] leading-snug text-zinc-500">{detail}</p>
    </div>
  );
}

function Breakdown({
  title,
  total,
  rows,
}: {
  title: string;
  total: number;
  rows: { label: string; value: number; bar: string }[];
}) {
  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-zinc-200">{title}</h3>
        <span className="text-[11px] text-zinc-500">{fmt(total)} total</span>
      </div>
      <div className="mt-4 space-y-3">
        {rows.map((row) => {
          const pct = total > 0 ? Math.round((row.value / total) * 100) : 0;
          return (
            <div key={row.label}>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-zinc-400">{row.label}</span>
                <span className="font-mono text-zinc-300">
                  {fmt(row.value)} <span className="text-zinc-600">({pct}%)</span>
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full rounded-full ${row.bar}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-zinc-500">{label}</dt>
      <dd className={`font-mono ${tone ?? "text-zinc-200"}`}>{value}</dd>
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  total,
  loading,
  onPrev,
  onNext,
}: {
  page: number;
  totalPages: number;
  total: number;
  loading: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="mt-4 flex flex-col gap-2 border-t border-zinc-800/70 pt-4 text-xs sm:flex-row sm:items-center sm:justify-between">
      <span className="text-zinc-500">
        Page {page} of {totalPages} · {fmt(total)} records
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={loading || page <= 1}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-40"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Previous
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={loading || page >= totalPages}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1.5 font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-40"
        >
          Next
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

type FlagTarget = { target_type: FlagTargetType; target_id: string; label: string };

function FlagDialog({
  target,
  reason,
  severity,
  details,
  busy,
  onReason,
  onSeverity,
  onDetails,
  onCancel,
  onSubmit,
}: {
  target: FlagTarget;
  reason: string;
  severity: FlagSeverity;
  details: string;
  busy: boolean;
  onReason: (value: string) => void;
  onSeverity: (value: FlagSeverity) => void;
  onDetails: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-2xl border border-zinc-800 bg-zinc-950 p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
              <Flag className="h-4 w-4 text-rose-400" />
              Flag {TARGET_LABELS[target.target_type].toLowerCase()}
            </h3>
            <p className="mt-1 text-xs text-zinc-500">{target.label}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200"
            aria-label="Close flag dialog"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="block text-xs text-zinc-400">
            Reason
            <input
              value={reason}
              onChange={(e) => onReason(e.target.value)}
              placeholder="e.g. Asks candidates for a registration fee"
              maxLength={160}
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-rose-500 focus:outline-none"
            />
          </label>
          <label className="block text-xs text-zinc-400">
            Severity
            <select
              value={severity}
              onChange={(e) => onSeverity(e.target.value as FlagSeverity)}
              className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 focus:border-rose-500 focus:outline-none"
            >
              <option value="low">Low — monitor</option>
              <option value="medium">Medium — review soon</option>
              <option value="high">High — act now</option>
            </select>
          </label>
          <label className="block text-xs text-zinc-400">
            Details (optional)
            <textarea
              value={details}
              onChange={(e) => onDetails(e.target.value)}
              rows={3}
              placeholder="What did you see? Links, quotes, evidence…"
              className="mt-1.5 w-full resize-none rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-rose-500 focus:outline-none"
            />
          </label>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-zinc-800 px-3 py-2 text-xs font-semibold text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy || reason.trim().length < 3}
            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Flag className="h-3.5 w-3.5" />}
            Raise flag
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();

  const [activeTab, setActiveTab] = useState<TabId>("pulse");
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // overview + ops (loaded from the database on every refresh)
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [usage, setUsage] = useState<LlmUsageResponse | null>(null);
  const [failures, setFailures] = useState<ParseFailuresResponse | null>(null);
  const [models, setModels] = useState<ModelRegistryItem[]>([]);
  const [config, setConfig] = useState<AdminConfigResponse | null>(null);
  const [editWeights, setEditWeights] = useState<Record<string, number>>({});
  const [configBusy, setConfigBusy] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  // users
  const [users, setUsers] = useState<AdminUsersResponse | null>(null);
  const [userInput, setUserInput] = useState("");
  const [userQuery, setUserQuery] = useState("");
  const [userRole, setUserRole] = useState("");
  const [userActive, setUserActive] = useState("");
  const [userPage, setUserPage] = useState(1);
  const [userReload, setUserReload] = useState(0);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userBusyId, setUserBusyId] = useState<string | null>(null);

  // employers
  const [employers, setEmployers] = useState<AdminEmployersResponse | null>(null);
  const [empInput, setEmpInput] = useState("");
  const [empQuery, setEmpQuery] = useState("");
  const [empVerified, setEmpVerified] = useState("");
  const [empPage, setEmpPage] = useState(1);
  const [empReload, setEmpReload] = useState(0);
  const [empLoading, setEmpLoading] = useState(false);
  const [empBusyId, setEmpBusyId] = useState<string | null>(null);
  const [ownerBusyId, setOwnerBusyId] = useState<string | null>(null);

  // moderation
  const [flags, setFlags] = useState<AdminFlagsResponse | null>(null);
  const [flagFilter, setFlagFilter] = useState("");
  const [flagReload, setFlagReload] = useState(0);
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [flagBusyId, setFlagBusyId] = useState<string | null>(null);
  const [suspiciousJobs, setSuspiciousJobs] = useState<AdminSuspiciousJobsResponse | null>(null);
  const [suspiciousEmployers, setSuspiciousEmployers] = useState<AdminEmployerItem[] | null>(null);
  const [suspiciousLoading, setSuspiciousLoading] = useState(false);
  const [takedownBusyId, setTakedownBusyId] = useState<string | null>(null);

  // flag dialog
  const [flagTarget, setFlagTarget] = useState<FlagTarget | null>(null);
  const [flagReason, setFlagReason] = useState("");
  const [flagSeverity, setFlagSeverity] = useState<FlagSeverity>("medium");
  const [flagDetails, setFlagDetails] = useState("");
  const [flagSubmitting, setFlagSubmitting] = useState(false);

  // skills + duplicate scan
  const [skills, setSkills] = useState<AdminSkillsResponse | null>(null);
  const [skillInput, setSkillInput] = useState("");
  const [skillQuery, setSkillQuery] = useState("");
  const [skillReload, setSkillReload] = useState(0);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [mergeBusy, setMergeBusy] = useState(false);
  const [mergeReport, setMergeReport] = useState<MergeReport | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicatesResponse | null>(null);
  const [duplicatesLoading, setDuplicatesLoading] = useState(false);

  const loadBootstrap = useCallback(
    async (silent = false) => {
      if (!token) return;
      if (!silent) setBootstrapLoading(true);
      const results = await Promise.allSettled([
        getAdminOverview(token),
        getLlmUsage(token),
        getParseFailures(token),
        getAdminModels(token),
        getAdminConfig(token),
      ]);

      const messages: string[] = [];
      const [overviewRes, usageRes, failuresRes, modelsRes, configRes] = results;

      if (overviewRes.status === "fulfilled") setOverview(overviewRes.value);
      else messages.push(errMessage(overviewRes.reason, "Failed to load overview"));
      if (usageRes.status === "fulfilled") setUsage(usageRes.value);
      else messages.push(errMessage(usageRes.reason, "Failed to load LLM usage"));
      if (failuresRes.status === "fulfilled") setFailures(failuresRes.value);
      else messages.push(errMessage(failuresRes.reason, "Failed to load parse failures"));
      if (modelsRes.status === "fulfilled") setModels(modelsRes.value.items);
      else messages.push(errMessage(modelsRes.reason, "Failed to load model registry"));
      if (configRes.status === "fulfilled") {
        setConfig(configRes.value);
        setEditWeights(
          Object.fromEntries(configRes.value.weights.map((w) => [w.component, w.weight])),
        );
      } else {
        messages.push(errMessage(configRes.reason, "Failed to load configuration"));
      }

      setError(messages.length > 0 ? messages[0] : null);
      setBootstrapLoading(false);
    },
    [token],
  );

  const loadUsers = useCallback(async () => {
    if (!token) return;
    setUsersLoading(true);
    try {
      const data = await getAdminUsers(token, {
        q: userQuery || undefined,
        role: userRole || undefined,
        is_active: userActive,
        page: userPage,
        limit: 20,
      });
      setUsers(data);
      setError(null);
    } catch (err) {
      setError(errMessage(err, "Failed to load users"));
    } finally {
      setUsersLoading(false);
    }
  }, [token, userQuery, userRole, userActive, userPage]);

  const loadEmployers = useCallback(async () => {
    if (!token) return;
    setEmpLoading(true);
    try {
      const data = await getAdminEmployers(token, {
        q: empQuery || undefined,
        verified: empVerified,
        page: empPage,
        limit: 20,
      });
      setEmployers(data);
      setError(null);
    } catch (err) {
      setError(errMessage(err, "Failed to load employers"));
    } finally {
      setEmpLoading(false);
    }
  }, [token, empQuery, empVerified, empPage]);

  const loadModeration = useCallback(async () => {
    if (!token) return;
    setFlagsLoading(true);
    setSuspiciousLoading(true);
    const results = await Promise.allSettled([
      getAdminFlags(token, { status: flagFilter || undefined, limit: 100 }),
      getSuspiciousJobs(token, { limit: 25 }),
      getSuspiciousEmployers(token, { limit: 25 }),
    ]);
    const [flagsRes, jobsRes, employersRes] = results;
    if (flagsRes.status === "fulfilled") setFlags(flagsRes.value);
    else setError(errMessage(flagsRes.reason, "Failed to load moderation flags"));
    if (jobsRes.status === "fulfilled") setSuspiciousJobs(jobsRes.value);
    else setError(errMessage(jobsRes.reason, "Failed to scan job listings"));
    if (employersRes.status === "fulfilled") setSuspiciousEmployers(employersRes.value.items);
    else setError(errMessage(employersRes.reason, "Failed to scan employers"));
    setFlagsLoading(false);
    setSuspiciousLoading(false);
  }, [token, flagFilter]);

  const loadSkills = useCallback(async () => {
    if (!token) return;
    setSkillsLoading(true);
    try {
      const data = await getAdminSkills(token, skillQuery || undefined);
      setSkills(data);
      setError(null);
    } catch (err) {
      setError(errMessage(err, "Failed to load skills"));
    } finally {
      setSkillsLoading(false);
    }
  }, [token, skillQuery]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (user && user.role !== "admin") {
      router.push("/dashboard");
    }
  }, [user, authLoading, router]);

  useEffect(() => {
    if (token && user?.role === "admin") void loadBootstrap();
  }, [token, user?.role, loadBootstrap]);

  useEffect(() => {
    if (token && user?.role === "admin" && activeTab === "users") void loadUsers();
  }, [token, user?.role, activeTab, loadUsers, userReload]);

  useEffect(() => {
    if (token && user?.role === "admin" && activeTab === "employers") void loadEmployers();
  }, [token, user?.role, activeTab, loadEmployers, empReload]);

  useEffect(() => {
    if (token && user?.role === "admin" && activeTab === "moderation") void loadModeration();
  }, [token, user?.role, activeTab, loadModeration, flagReload]);

  useEffect(() => {
    if (token && user?.role === "admin" && activeTab === "ops") void loadSkills();
  }, [token, user?.role, activeTab, loadSkills, skillReload]);

  const refreshAll = async () => {
    setRefreshing(true);
    await loadBootstrap(true);
    if (activeTab === "users") await loadUsers();
    if (activeTab === "employers") await loadEmployers();
    if (activeTab === "moderation") await loadModeration();
    if (activeTab === "ops") await loadSkills();
    setRefreshing(false);
    toast.success("Admin data refreshed from the database");
  };

  const submitUserSearch = (event: FormEvent) => {
    event.preventDefault();
    setUserPage(1);
    setUserQuery(userInput.trim());
    setUserReload((n) => n + 1);
  };

  const submitEmployerSearch = (event: FormEvent) => {
    event.preventDefault();
    setEmpPage(1);
    setEmpQuery(empInput.trim());
    setEmpReload((n) => n + 1);
  };

  const submitSkillSearch = (event: FormEvent) => {
    event.preventDefault();
    setSkillQuery(skillInput.trim());
    setSkillReload((n) => n + 1);
  };

  const openFlagDialog = (
    target_type: FlagTargetType,
    target_id: string,
    label: string,
  ) => {
    setFlagTarget({ target_type, target_id, label });
    setFlagReason("");
    setFlagSeverity("medium");
    setFlagDetails("");
  };

  const submitFlag = async () => {
    if (!token || !flagTarget || flagSubmitting) return;
    if (flagReason.trim().length < 3) {
      toast.error("Give the flag a reason (at least 3 characters).");
      return;
    }
    setFlagSubmitting(true);
    try {
      await createAdminFlag(
        {
          target_type: flagTarget.target_type,
          target_id: flagTarget.target_id,
          reason: flagReason.trim(),
          severity: flagSeverity,
          details: flagDetails.trim() || undefined,
        },
        token,
      );
      toast.success(`Flag raised on ${flagTarget.label}`);
      setFlagTarget(null);
      await Promise.all([loadBootstrap(true), loadModeration()]);
    } catch (err) {
      toast.error(errMessage(err, "Failed to raise flag"));
    } finally {
      setFlagSubmitting(false);
    }
  };

  const resolveFlag = async (flag: AdminFlagItem, next: FlagStatus) => {
    if (!token || flagBusyId) return;
    let note: string | undefined;
    if (next !== "open") {
      const entered = window.prompt(
        next === "resolved"
          ? "Resolution note (what did you decide?)"
          : "Why are you dismissing this flag?",
      );
      if (entered === null) return;
      note = entered.trim() || undefined;
    }
    setFlagBusyId(flag.id);
    try {
      const result = await updateAdminFlag(flag.id, { status: next, resolution_note: note }, token);
      setFlags((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((row) => (row.id === flag.id ? result.flag : row)),
            }
          : prev,
      );
      toast.success(
        next === "open" ? "Flag re-opened" : next === "resolved" ? "Flag resolved" : "Flag dismissed",
      );
      await loadBootstrap(true);
    } catch (err) {
      toast.error(errMessage(err, "Failed to update flag"));
    } finally {
      setFlagBusyId(null);
    }
  };

  const toggleEmployerVerified = async (company: AdminEmployerItem) => {
    if (!token || empBusyId) return;
    setEmpBusyId(company.id);
    try {
      const result = await updateAdminEmployer(
        company.id,
        { is_verified: !company.is_verified },
        token,
      );
      const patch = (row: AdminEmployerItem) =>
        row.id === company.id ? { ...row, is_verified: result.company.is_verified } : row;
      setEmployers((prev) => (prev ? { ...prev, items: prev.items.map(patch) } : prev));
      setSuspiciousEmployers((prev) => (prev ? prev.map(patch) : prev));
      toast.success(
        result.company.is_verified
          ? `${company.name} verified`
          : `${company.name} verification removed`,
      );
      await loadBootstrap(true);
    } catch (err) {
      toast.error(errMessage(err, "Failed to update employer"));
    } finally {
      setEmpBusyId(null);
    }
  };

  const toggleEmployerOwner = async (company: AdminEmployerItem) => {
    if (!token || ownerBusyId) return;
    const deactivate = company.owner.is_active;
    if (
      deactivate &&
      !window.confirm(
        `Suspend the owner of ${company.name}? ${company.owner.email} will be signed out and can no longer post.`,
      )
    ) {
      return;
    }
    setOwnerBusyId(company.id);
    try {
      const result = await updateAdminUser(
        company.owner.id,
        { is_active: !company.owner.is_active },
        token,
      );
      const patch = (row: AdminEmployerItem) =>
        row.id === company.id
          ? { ...row, owner: { ...row.owner, is_active: result.user.is_active } }
          : row;
      setEmployers((prev) => (prev ? { ...prev, items: prev.items.map(patch) } : prev));
      setSuspiciousEmployers((prev) => (prev ? prev.map(patch) : prev));
      toast.success(
        result.user.is_active
          ? `${company.owner.email} reinstated`
          : `${company.owner.email} suspended`,
      );
      await loadBootstrap(true);
    } catch (err) {
      toast.error(errMessage(err, "Failed to update owner account"));
    } finally {
      setOwnerBusyId(null);
    }
  };

  const takeDownJob = async (jobId: string, title: string) => {
    if (!token || takedownBusyId) return;
    if (!window.confirm(`Take down "${title}"? It will be closed and hidden from job seekers.`)) {
      return;
    }
    setTakedownBusyId(jobId);
    try {
      await updateAdminJobStatus(jobId, "closed", token);
      toast.success(`"${title}" taken down`);
      await Promise.all([loadBootstrap(true), loadModeration()]);
    } catch (err) {
      toast.error(errMessage(err, "Failed to take down posting"));
    } finally {
      setTakedownBusyId(null);
    }
  };

  const handleToggleUser = async (item: AdminUserItem) => {
    if (!token || userBusyId) return;
    if (item.is_active && !window.confirm(`Deactivate ${item.email}? They will be signed out.`)) {
      return;
    }
    setUserBusyId(item.id);
    try {
      const result = await updateAdminUser(
        item.id,
        { is_active: !item.is_active },
        token,
      );
      setUsers((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((row) =>
                row.id === item.id ? { ...row, is_active: result.user.is_active } : row,
              ),
            }
          : prev,
      );
      toast.success(
        result.user.is_active ? `${item.email} activated` : `${item.email} deactivated`,
      );
      await loadBootstrap(true);
    } catch (err) {
      toast.error(errMessage(err, "Failed to update account"));
    } finally {
      setUserBusyId(null);
    }
  };

  const handleRoleChange = async (item: AdminUserItem, role: UserRole) => {
    if (!token || userBusyId || role === item.role) return;
    setUserBusyId(item.id);
    try {
      const result = await updateAdminUser(item.id, { role }, token);
      setUsers((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((row) =>
                row.id === item.id ? { ...row, role: result.user.role as UserRole } : row,
              ),
            }
          : prev,
      );
      toast.success(`${item.email} is now ${ROLE_LABELS[result.user.role as UserRole]}`);
    } catch (err) {
      toast.error(errMessage(err, "Failed to change role"));
    } finally {
      setUserBusyId(null);
    }
  };

  const handleMerge = async () => {
    if (!token || !sourceId || !targetId || sourceId === targetId) return;
    const source = skills?.items.find((s) => s.id === sourceId);
    const target = skills?.items.find((s) => s.id === targetId);
    if (
      !window.confirm(
        `Merge "${source?.name ?? "source"}" into "${target?.name ?? "target"}"? ` +
          "Profiles, jobs, aliases, edges and affinities are re-pointed in one transaction.",
      )
    ) {
      return;
    }
    setMergeBusy(true);
    try {
      const report = await mergeSkills(sourceId, targetId, token);
      setMergeReport(report);
      setSourceId("");
      setTargetId("");
      await loadSkills();
      await loadBootstrap(true);
      toast.success(`Merged "${report.source.name}" into "${report.target.name}"`);
    } catch (err) {
      toast.error(errMessage(err, "Skill merge failed"));
    } finally {
      setMergeBusy(false);
    }
  };

  const scanDuplicates = async () => {
    if (!token) return;
    setDuplicatesLoading(true);
    try {
      const data = await getJobDuplicates(token);
      setDuplicates(data);
      setError(null);
      toast.success(`Scanned ${data.jobs_examined} embedded jobs`);
    } catch (err) {
      toast.error(errMessage(err, "Duplicate scan failed"));
    } finally {
      setDuplicatesLoading(false);
    }
  };

  const handleRetry = async (resumeId: string) => {
    if (!token) return;
    setRetryingId(resumeId);
    try {
      await retryParse(resumeId, token);
      setFailures(await getParseFailures(token));
      toast.success("Resume parse queued for retry");
    } catch (err) {
      toast.error(errMessage(err, "Retry failed"));
    } finally {
      setRetryingId(null);
    }
  };

  const weightSum = Object.values(editWeights).reduce(
    (sum, value) => sum + (Number.isFinite(value) ? value : 0),
    0,
  );
  const sumValid = Math.abs(weightSum - 1) < 0.0005;

  const handleSaveConfig = async () => {
    if (!token) return;
    setConfigBusy(true);
    try {
      const saved = await putAdminConfig(editWeights, token);
      toast.success(`Weights saved — Σw = ${saved.sum}`);
      await loadBootstrap(true);
    } catch (err) {
      toast.error(errMessage(err, "Saving weights failed"));
    } finally {
      setConfigBusy(false);
    }
  };

  if (authLoading || bootstrapLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-rose-500 border-t-transparent" />
          <p className="text-sm text-zinc-500">Loading admin console…</p>
        </div>
      </div>
    );
  }

  if (!user || user.role !== "admin") return null;

  const attention = (overview?.parse_failures.failed ?? 0) + (overview?.parse_failures.stuck ?? 0);
  const openFlags = overview?.moderation.open_flags ?? 0;

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 border-b border-zinc-800/80 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-rose-400">
            <ShieldCheck className="h-4 w-4" />
            Admin Console
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
            Marketplace health
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-400">
            Live usage, hiring outcomes and trust &amp; safety across both sides of the
            marketplace. Employers run their own postings — this console watches the system.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-right text-[11px] leading-tight text-zinc-500">
            {overview ? (
              <>
                Synced <span className="text-zinc-400">{formatDateTime(overview.generated_at)}</span>
                <br />
                Signed in as <span className="text-zinc-400">{user.email}</span>
              </>
            ) : (
              "Not synced yet"
            )}
          </span>
          <button
            type="button"
            onClick={refreshAll}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3.5 py-2 text-xs font-semibold text-zinc-300 transition-colors hover:border-rose-500/40 hover:text-rose-300 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="mt-6 overflow-x-auto">
        <div className="inline-flex min-w-full gap-1 rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-1 sm:min-w-0">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            const badge =
              tab.id === "moderation" && openFlags > 0 ? openFlags : undefined;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                  active
                    ? "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30"
                    : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
                {badge !== undefined && (
                  <span className="rounded-full bg-rose-500 px-1.5 py-0.5 text-[9px] font-bold text-white">
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ---------------- Pulse ---------------- */}
      {activeTab === "pulse" && (
        <div className="mt-6 space-y-6">
          {!overview ? (
            <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-8 text-center text-sm text-zinc-500">
              No overview data available. Use Refresh to retry.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatCard
                  label="Online now"
                  value={fmt(overview.users.online_now)}
                  detail="Active in the last 5 minutes"
                  icon={Radio}
                  accent="text-emerald-400"
                  live
                />
                <StatCard
                  label="Active today"
                  value={fmt(overview.users.active_today)}
                  detail={`${fmt(overview.users.active_week)} this week · ${fmt(overview.users.active_month)} this month`}
                  icon={Zap}
                  accent="text-teal-400"
                />
                <StatCard
                  label="Job seekers hired"
                  value={fmt(overview.applications.job_seekers_hired)}
                  detail={`${fmt(overview.applications.hires)} hires · ${overview.applications.hire_rate}% of applicants`}
                  icon={Trophy}
                  accent="text-amber-400"
                />
                <StatCard
                  label="Open flags"
                  value={fmt(overview.moderation.open_flags)}
                  detail={`${fmt(overview.moderation.high_severity_flags)} high severity · ${fmt(overview.moderation.resolved_last_7d)} resolved this week`}
                  icon={ShieldAlert}
                  accent={openFlags > 0 ? "text-rose-400" : "text-zinc-500"}
                />
              </div>

              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <StatCard
                  label="Job seekers"
                  value={fmt(overview.users.job_seekers)}
                  detail={`${fmt(overview.users.new_last_7d)} new accounts this week`}
                  icon={Users}
                  accent="text-cyan-400"
                />
                <StatCard
                  label="Employers"
                  value={fmt(overview.users.employers)}
                  detail={`${fmt(overview.companies.with_published_jobs)} with live postings`}
                  icon={Building2}
                  accent="text-indigo-400"
                />
                <StatCard
                  label="Published jobs"
                  value={fmt(overview.jobs.published)}
                  detail={`${fmt(overview.jobs.new_last_7d)} added this week`}
                  icon={CheckCircle2}
                  accent="text-teal-400"
                />
                <StatCard
                  label="Applications"
                  value={fmt(overview.applications.total)}
                  detail={`${fmt(overview.applications.last_7d)} in the last 7 days`}
                  icon={Activity}
                  accent="text-violet-400"
                />
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-baseline justify-between">
                    <h3 className="text-sm font-semibold text-zinc-200">Live usage</h3>
                    <span className="text-[11px] text-zinc-500">
                      {fmt(overview.users.total)} accounts
                    </span>
                  </div>
                  <div className="mt-4 space-y-3">
                    {[
                      { label: "Online now", value: overview.users.online_now, bar: "bg-emerald-400" },
                      { label: "Today", value: overview.users.active_today, bar: "bg-teal-400" },
                      { label: "This week", value: overview.users.active_week, bar: "bg-cyan-400" },
                      { label: "This month", value: overview.users.active_month, bar: "bg-indigo-400" },
                    ].map((row) => {
                      const pct =
                        overview.users.total > 0
                          ? Math.round((row.value / overview.users.total) * 100)
                          : 0;
                      return (
                        <div key={row.label}>
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-zinc-400">{row.label}</span>
                            <span className="font-mono text-zinc-300">
                              {fmt(row.value)} <span className="text-zinc-600">({pct}%)</span>
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-800">
                            <div
                              className={`h-full rounded-full ${row.bar}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <p className="mt-3 text-[10px] leading-relaxed text-zinc-600">
                    Presence is refreshed on authenticated requests and throttled to one write
                    every two minutes per account.
                  </p>
                </div>

                <Breakdown
                  title="Audience"
                  total={overview.users.total}
                  rows={[
                    { label: "Job seekers", value: overview.users.job_seekers, bar: "bg-teal-400" },
                    { label: "Employers", value: overview.users.employers, bar: "bg-indigo-400" },
                    { label: "Admins", value: overview.users.admins, bar: "bg-rose-400" },
                    { label: "Deactivated", value: overview.users.deactivated, bar: "bg-zinc-500" },
                  ]}
                />

                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <div className="flex items-center justify-between">
                    <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                      <Trophy className="h-4 w-4 text-amber-400" />
                      Hiring outcomes
                    </h3>
                    <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300 ring-1 ring-inset ring-amber-500/30">
                      {overview.applications.hire_rate}% hire rate
                    </span>
                  </div>
                  <dl className="mt-4 space-y-2.5 text-xs">
                    <MetricRow label="Job seekers hired" value={fmt(overview.applications.job_seekers_hired)} tone="text-amber-300" />
                    <MetricRow label="Total hires" value={fmt(overview.applications.hires)} />
                    <MetricRow label="Hires last 30d" value={fmt(overview.applications.hires_last_30d)} />
                    <MetricRow label="Open offers" value={fmt(overview.applications.offers)} />
                    <MetricRow label="Applicants" value={fmt(overview.applications.applicants)} />
                    <MetricRow label="Employers with hires" value={fmt(overview.applications.employers_with_hires)} />
                  </dl>
                  <p className="mt-3 text-[10px] leading-relaxed text-zinc-600">
                    A hire is a real terminal pipeline stage, not an inferred offer.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Building2 className="h-4 w-4 text-indigo-400" />
                    Employer health
                  </h3>
                  <dl className="mt-4 space-y-2.5 text-xs">
                    <MetricRow label="Companies" value={fmt(overview.companies.total)} />
                    <MetricRow label="Verified" value={fmt(overview.companies.verified)} tone="text-emerald-300" />
                    <MetricRow label="Unverified" value={fmt(overview.companies.unverified)} tone="text-amber-300" />
                    <MetricRow label="Active owners" value={fmt(overview.companies.active_owners)} />
                    <MetricRow label="With live postings" value={fmt(overview.companies.with_published_jobs)} />
                    <MetricRow label="New this week" value={fmt(overview.companies.new_last_7d)} />
                  </dl>
                  <button
                    type="button"
                    onClick={() => setActiveTab("employers")}
                    className="mt-4 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:border-indigo-500/40 hover:text-indigo-300"
                  >
                    Review employers
                  </button>
                </div>

                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <ShieldAlert className="h-4 w-4 text-rose-400" />
                    Trust &amp; safety
                  </h3>
                  <dl className="mt-4 space-y-2.5 text-xs">
                    <MetricRow label="Open flags" value={fmt(overview.moderation.open_flags)} tone={openFlags > 0 ? "text-rose-300" : "text-zinc-200"} />
                    <MetricRow label="High severity" value={fmt(overview.moderation.high_severity_flags)} tone="text-rose-300" />
                    <MetricRow label="Flagged jobs" value={fmt(overview.moderation.flagged_jobs)} />
                    <MetricRow label="Flagged employers" value={fmt(overview.moderation.flagged_companies)} />
                    <MetricRow label="Flagged accounts" value={fmt(overview.moderation.flagged_users)} />
                    <MetricRow label="Resolved last 7d" value={fmt(overview.moderation.resolved_last_7d)} tone="text-emerald-300" />
                  </dl>
                  <button
                    type="button"
                    onClick={() => setActiveTab("moderation")}
                    className="mt-4 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:border-rose-500/40 hover:text-rose-300"
                  >
                    Open moderation queue
                  </button>
                </div>

                <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Database className="h-4 w-4 text-zinc-400" />
                    Data &amp; ops health
                  </h3>
                  <dl className="mt-4 space-y-2.5 text-xs">
                    <MetricRow label="Profiles with résumé" value={`${fmt(overview.profiles.with_resume)} / ${fmt(overview.profiles.total)}`} />
                    <MetricRow label="Failed résumé parses" value={fmt(overview.parse_failures.failed)} tone={overview.parse_failures.failed > 0 ? "text-rose-300" : "text-zinc-200"} />
                    <MetricRow label="Stuck résumé parses" value={fmt(overview.parse_failures.stuck)} tone={overview.parse_failures.stuck > 0 ? "text-amber-300" : "text-zinc-200"} />
                    <MetricRow label="LLM calls" value={fmt(overview.llm.calls)} />
                    <MetricRow label="Flagged LLM calls" value={fmt(overview.llm.flagged)} />
                    <MetricRow label="Needs attention" value={fmt(attention)} />
                  </dl>
                  <button
                    type="button"
                    onClick={() => setActiveTab("ops")}
                    className="mt-4 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
                  >
                    Review AI &amp; ops
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
                  <Activity className="h-4 w-4 text-zinc-400" />
                  Application pipeline
                </h3>
                <div className="mt-4 flex flex-wrap gap-2">
                  {Object.entries(overview.applications.by_status).length === 0 && (
                    <p className="text-xs text-zinc-500">No applications recorded yet.</p>
                  )}
                  {Object.entries(overview.applications.by_status).map(([status, count]) => (
                    <span
                      key={status}
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] ${
                        status === "hired"
                          ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                          : "border-zinc-800 bg-zinc-950/60 text-zinc-300"
                      }`}
                    >
                      <span className="capitalize text-zinc-500">{status.replace(/_/g, " ")}</span>
                      <span className="font-mono font-semibold text-zinc-100">{fmt(count)}</span>
                    </span>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ---------------- Users ---------------- */}
      {activeTab === "users" && (
        <section className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                <Users className="h-4 w-4 text-teal-400" />
                Accounts
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Presence, outcomes and account controls. Changes are written to the database immediately.
              </p>
            </div>
            <span className="text-[11px] text-zinc-500">
              {users ? `${fmt(users.total)} matching accounts` : "Loading…"}
            </span>
          </div>

          <form onSubmit={submitUserSearch} className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                placeholder="Search by email…"
                className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <select
              value={userRole}
              onChange={(e) => {
                setUserRole(e.target.value);
                setUserPage(1);
              }}
              aria-label="Filter by role"
              className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
            >
              <option value="">All roles</option>
              {ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </select>
            <select
              value={userActive}
              onChange={(e) => {
                setUserActive(e.target.value);
                setUserPage(1);
              }}
              aria-label="Filter by status"
              className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
            >
              <option value="">All statuses</option>
              <option value="true">Active</option>
              <option value="false">Deactivated</option>
            </select>
            <div className="flex gap-2">
              <button
                type="submit"
                className="flex-1 rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
              >
                Search
              </button>
              <button
                type="button"
                onClick={() => {
                  setUserInput("");
                  setUserQuery("");
                  setUserRole("");
                  setUserActive("");
                  setUserPage(1);
                  setUserReload((n) => n + 1);
                }}
                className="rounded-lg border border-zinc-800 px-3 py-2 text-xs font-semibold text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              >
                Reset
              </button>
            </div>
          </form>

          <div className="mt-5 overflow-x-auto">
            {!users ? (
              <div className="flex items-center justify-center py-10 text-zinc-500">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : users.items.length === 0 ? (
              <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                No accounts match the current filters.
              </div>
            ) : (
              <table className={`w-full min-w-[900px] text-left text-xs ${usersLoading ? "opacity-60" : ""}`}>
                <thead>
                  <tr className="text-zinc-500">
                    <th className="pb-2 font-medium">Account</th>
                    <th className="pb-2 font-medium">Role</th>
                    <th className="pb-2 font-medium">Last seen</th>
                    <th className="pb-2 font-medium">Outcomes</th>
                    <th className="pb-2 font-medium">Trust</th>
                    <th className="pb-2 text-right font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="text-zinc-300">
                  {users.items.map((item) => {
                    const name =
                      [item.profile?.first_name, item.profile?.last_name]
                        .filter(Boolean)
                        .join(" ") || item.email.split("@")[0];
                    const isSelf = item.id === user.id;
                    return (
                      <tr key={item.id} className="border-t border-zinc-800/60 align-middle">
                        <td className="py-2.5 pr-4">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-zinc-100">{name}</span>
                            {isSelf && (
                              <span className="rounded bg-rose-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase text-rose-300">
                                You
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-zinc-500">{item.email}</p>
                          {item.profile?.headline && (
                            <p className="max-w-[260px] truncate text-[10px] text-zinc-600">
                              {item.profile.headline}
                            </p>
                          )}
                        </td>
                        <td className="py-2.5 pr-4">
                          <select
                            value={item.role}
                            onChange={(e) => handleRoleChange(item, e.target.value as UserRole)}
                            disabled={isSelf || userBusyId === item.id}
                            aria-label={`Role for ${item.email}`}
                            className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-2 py-1 text-[11px] text-zinc-200 focus:border-teal-500 focus:outline-none disabled:opacity-50"
                          >
                            {ROLE_OPTIONS.map((role) => (
                              <option key={role} value={role}>
                                {ROLE_LABELS[role]}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2.5 pr-4 text-[11px] text-zinc-400">
                          {relativeTime(item.last_active_at)}
                          <br />
                          <span className="text-zinc-600">joined {formatDate(item.created_at)}</span>
                        </td>
                        <td className="py-2.5 pr-4 text-[11px] text-zinc-400">
                          {fmt(item.applications)} applications
                          <br />
                          <span className={item.hired > 0 ? "text-amber-300" : "text-zinc-600"}>
                            {fmt(item.hired)} hires
                          </span>
                          <span className="text-zinc-600"> · {fmt(item.companies)} companies</span>
                        </td>
                        <td className="py-2.5 pr-4">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${
                                item.is_verified
                                  ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                                  : "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30"
                              }`}
                            >
                              <BadgeCheck className="h-3 w-3" />
                              {item.is_verified ? "Verified" : "Unverified"}
                            </span>
                            {item.open_flags > 0 && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300 ring-1 ring-inset ring-rose-500/30">
                                <Flag className="h-3 w-3" />
                                {fmt(item.open_flags)} flags
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={() => openFlagDialog("user", item.id, item.email)}
                              className="rounded-lg border border-zinc-800 px-2 py-0.5 text-[10px] font-semibold text-zinc-400 hover:border-rose-500/40 hover:text-rose-300"
                            >
                              Flag
                            </button>
                          </div>
                        </td>
                        <td className="py-2.5 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <span
                              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${
                                item.is_active
                                  ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                                  : "bg-zinc-500/10 text-zinc-400 ring-zinc-500/30"
                              }`}
                            >
                              {item.is_active ? "Active" : "Inactive"}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleToggleUser(item)}
                              disabled={isSelf || userBusyId === item.id}
                              className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold transition-colors disabled:opacity-40 ${
                                item.is_active
                                  ? "border-rose-500/30 text-rose-300 hover:bg-rose-500/10"
                                  : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10"
                              }`}
                            >
                              {userBusyId === item.id ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : null}
                              {item.is_active ? "Deactivate" : "Activate"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {users && (
            <Pagination
              page={users.page}
              totalPages={users.total_pages}
              total={users.total}
              loading={usersLoading}
              onPrev={() => setUserPage((p) => Math.max(1, p - 1))}
              onNext={() => setUserPage((p) => p + 1)}
            />
          )}
        </section>
      )}

      {/* ---------------- Employers ---------------- */}
      {activeTab === "employers" && (
        <section className="mt-6 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                <Building2 className="h-4 w-4 text-indigo-400" />
                Employer directory
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Company accounts with posting, applicant and hire aggregates. Verify real
                businesses; watch the ones that never convert.
              </p>
            </div>
            <span className="text-[11px] text-zinc-500">
              {employers ? `${fmt(employers.total)} companies` : "Loading…"}
            </span>
          </div>

          <form onSubmit={submitEmployerSearch} className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
              <input
                value={empInput}
                onChange={(e) => setEmpInput(e.target.value)}
                placeholder="Search company or owner email…"
                className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
              />
            </div>
            <select
              value={empVerified}
              onChange={(e) => {
                setEmpVerified(e.target.value);
                setEmpPage(1);
              }}
              aria-label="Filter by verification"
              className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
            >
              <option value="">All verification states</option>
              <option value="true">Verified</option>
              <option value="false">Unverified</option>
            </select>
            <button
              type="submit"
              className="rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => {
                setEmpInput("");
                setEmpQuery("");
                setEmpVerified("");
                setEmpPage(1);
                setEmpReload((n) => n + 1);
              }}
              className="rounded-lg border border-zinc-800 px-3 py-2 text-xs font-semibold text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
            >
              Reset
            </button>
          </form>

          <div className="mt-5 overflow-x-auto">
            {!employers ? (
              <div className="flex items-center justify-center py-10 text-zinc-500">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : employers.items.length === 0 ? (
              <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                No employers match the current filters.
              </div>
            ) : (
              <table className={`w-full min-w-[980px] text-left text-xs ${empLoading ? "opacity-60" : ""}`}>
                <thead>
                  <tr className="text-zinc-500">
                    <th className="pb-2 font-medium">Employer</th>
                    <th className="pb-2 font-medium">Owner</th>
                    <th className="pb-2 font-medium">Postings</th>
                    <th className="pb-2 font-medium">Outcomes</th>
                    <th className="pb-2 font-medium">Risk</th>
                    <th className="pb-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-zinc-300">
                  {employers.items.map((item) => (
                    <tr key={item.id} className="border-t border-zinc-800/60 align-top">
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-zinc-100">{item.name}</span>
                          {item.is_verified ? (
                            <BadgeCheck className="h-3.5 w-3.5 text-emerald-400" />
                          ) : (
                            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-bold uppercase text-amber-300">
                              Unverified
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-zinc-500">
                          {item.industry || "No industry"} · {item.location || "No location"}
                        </p>
                        {item.website && (
                          <a
                            href={item.website}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-[10px] text-zinc-600 hover:text-teal-300"
                          >
                            {item.website}
                            <ExternalLink className="h-2.5 w-2.5" />
                          </a>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-[11px] text-zinc-400">
                        {item.owner.email}
                        <br />
                        <span className="text-zinc-600">
                          {item.owner.is_active ? "active" : "deactivated"} ·{" "}
                          {relativeTime(item.owner.last_active_at)}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-[11px] text-zinc-400">
                        <span className="font-mono text-zinc-200">{fmt(item.postings.published)}</span> live
                        <br />
                        <span className="text-zinc-600">
                          {fmt(item.postings.total)} total · {fmt(item.postings.last_7d)} this week
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-[11px] text-zinc-400">
                        {fmt(item.applications)} applicants
                        <br />
                        <span className={item.hires > 0 ? "text-amber-300" : "text-zinc-600"}>
                          {fmt(item.hires)} hires
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${riskTone(item.risk_score)}`}
                        >
                          <ShieldAlert className="h-3 w-3" />
                          {item.risk_score}
                        </span>
                        {item.open_flags > 0 && (
                          <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-300 ring-1 ring-inset ring-rose-500/30">
                            {fmt(item.open_flags)} flags
                          </span>
                        )}
                        {item.risk_reasons.length > 0 && (
                          <ul className="mt-1.5 max-w-[240px] list-disc space-y-0.5 pl-3 text-[10px] leading-snug text-zinc-600">
                            {item.risk_reasons.slice(0, 3).map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        <div className="flex flex-col items-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleEmployerVerified(item)}
                            disabled={empBusyId === item.id}
                            className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold disabled:opacity-40 ${
                              item.is_verified
                                ? "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
                                : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10"
                            }`}
                          >
                            {empBusyId === item.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <BadgeCheck className="h-3 w-3" />
                            )}
                            {item.is_verified ? "Unverify" : "Verify"}
                          </button>
                          <button
                            type="button"
                            onClick={() => openFlagDialog("company", item.id, item.name)}
                            className="inline-flex items-center gap-1 rounded-lg border border-rose-500/30 px-2 py-1 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/10"
                          >
                            <Flag className="h-3 w-3" />
                            Flag
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleEmployerOwner(item)}
                            disabled={ownerBusyId === item.id}
                            className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold disabled:opacity-40 ${
                              item.owner.is_active
                                ? "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
                                : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10"
                            }`}
                          >
                            {ownerBusyId === item.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <UserX className="h-3 w-3" />
                            )}
                            {item.owner.is_active ? "Suspend owner" : "Reinstate owner"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {employers && (
            <Pagination
              page={employers.page}
              totalPages={employers.total_pages}
              total={employers.total}
              loading={empLoading}
              onPrev={() => setEmpPage((p) => Math.max(1, p - 1))}
              onNext={() => setEmpPage((p) => p + 1)}
            />
          )}
        </section>
      )}

      {/* ---------------- Moderation ---------------- */}
      {activeTab === "moderation" && (
        <div className="mt-6 space-y-6">
          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <Flag className="h-4 w-4 text-rose-400" />
                  Flag queue
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Human decisions on suspicious jobs, employers and accounts. Every flag keeps an
                  audit trail.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {(["", "open", "resolved", "dismissed"] as const).map((value) => (
                  <button
                    key={value || "all"}
                    type="button"
                    onClick={() => {
                      setFlagFilter(value);
                      setFlagReload((n) => n + 1);
                    }}
                    className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold capitalize ${
                      flagFilter === value
                        ? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                        : "border-zinc-800 text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {value || "all"}
                    {flags?.counts[value || "open"] !== undefined && value !== "" && (
                      <span className="ml-1 text-zinc-500">{flags.counts[value]}</span>
                    )}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setFlagReload((n) => n + 1)}
                  disabled={flagsLoading}
                  className="inline-flex items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-400 hover:text-zinc-200 disabled:opacity-50"
                >
                  <RefreshCw className={`h-3 w-3 ${flagsLoading ? "animate-spin" : ""}`} />
                  Reload
                </button>
              </div>
            </div>

            <div className="mt-4 space-y-2">
              {flagsLoading && !flags ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : !flags || flags.items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  No flags match this filter. Use the scans below to triage suspicious activity.
                </div>
              ) : (
                flags.items.map((flag) => (
                  <div
                    key={flag.id}
                    className="rounded-xl border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${SEVERITY_STYLES[flag.severity]}`}
                      >
                        {flag.severity}
                      </span>
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-semibold text-zinc-300">
                        {TARGET_LABELS[flag.target_type]}
                      </span>
                      <span className="font-semibold text-zinc-100">
                        {flag.target_label || flag.target_id.slice(0, 8)}
                      </span>
                      <span
                        className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ring-1 ring-inset ${FLAG_STATUS_STYLES[flag.status]}`}
                      >
                        {flag.status}
                      </span>
                    </div>
                    <p className="mt-1.5 text-zinc-300">{flag.reason}</p>
                    {flag.details && (
                      <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-zinc-500">
                        {flag.details}
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-zinc-600">
                      <span>raised {formatDateTime(flag.created_at)}</span>
                      {flag.created_by && <span>· by {flag.created_by}</span>}
                      {flag.resolved_at && (
                        <span>
                          · {flag.status} {formatDateTime(flag.resolved_at)}
                          {flag.resolved_by ? ` by ${flag.resolved_by}` : ""}
                        </span>
                      )}
                      {flag.resolution_note && (
                        <span className="text-zinc-500">· “{flag.resolution_note}”</span>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {flag.target_type === "job" && (
                        <Link
                          href={`/jobs/${flag.target_id}`}
                          className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
                        >
                          Open posting
                          <ArrowUpRight className="h-2.5 w-2.5" />
                        </Link>
                      )}
                      {flag.status !== "open" && (
                        <button
                          type="button"
                          onClick={() => resolveFlag(flag, "open")}
                          disabled={flagBusyId === flag.id}
                          className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-300 hover:border-amber-500/40 hover:text-amber-300 disabled:opacity-40"
                        >
                          Re-open
                        </button>
                      )}
                      {flag.status === "open" && (
                        <>
                          <button
                            type="button"
                            onClick={() => resolveFlag(flag, "resolved")}
                            disabled={flagBusyId === flag.id}
                            className="inline-flex items-center gap-1 rounded border border-emerald-500/30 px-2 py-1 text-[10px] font-semibold text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40"
                          >
                            {flagBusyId === flag.id ? (
                              <Loader2 className="h-2.5 w-2.5 animate-spin" />
                            ) : (
                              <CheckCircle2 className="h-2.5 w-2.5" />
                            )}
                            Resolve
                          </button>
                          <button
                            type="button"
                            onClick={() => resolveFlag(flag, "dismissed")}
                            disabled={flagBusyId === flag.id}
                            className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-400 hover:text-zinc-200 disabled:opacity-40"
                          >
                            <Ban className="h-2.5 w-2.5" />
                            Dismiss
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  Suspicious listings
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Explainable heuristics — scam phrasing, contact details, salary anomalies and
                  account trust. Scores are triage, not verdicts.
                </p>
              </div>
              <span className="text-[11px] text-zinc-500">
                {suspiciousJobs
                  ? `${suspiciousJobs.items.length} of ${fmt(suspiciousJobs.scanned)} scanned · threshold ${suspiciousJobs.threshold}`
                  : "Scanning…"}
              </span>
            </div>

            <div className="mt-4 space-y-2">
              {suspiciousLoading && !suspiciousJobs ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : !suspiciousJobs || suspiciousJobs.items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  No listings above the risk threshold.
                </div>
              ) : (
                suspiciousJobs.items.map((job) => (
                  <div
                    key={job.id}
                    className="rounded-xl border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${riskTone(job.risk_score)}`}
                      >
                        <ShieldAlert className="h-3 w-3" />
                        risk {job.risk_score}
                      </span>
                      <Link
                        href={`/jobs/${job.id}`}
                        className="inline-flex items-center gap-1 font-semibold text-zinc-100 hover:text-teal-300"
                      >
                        {job.title}
                        <ExternalLink className="h-3 w-3 opacity-60" />
                      </Link>
                      <span className="text-[10px] uppercase tracking-wider text-zinc-600">
                        {job.source}
                      </span>
                      <span className="ml-auto text-[10px] text-zinc-500">
                        {job.status} · {fmt(job.applicants)} applicants
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-zinc-500">
                      {job.company.name}
                      {job.company.is_verified ? " · verified" : " · unverified"} ·{" "}
                      {job.location}
                      {job.is_remote ? " · remote" : ""}
                    </p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {job.risk_reasons.map((reason) => (
                        <li
                          key={reason}
                          className="rounded bg-zinc-800/70 px-1.5 py-0.5 text-[10px] text-zinc-400"
                        >
                          {reason}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => openFlagDialog("job", job.id, job.title)}
                        className="inline-flex items-center gap-1 rounded border border-rose-500/30 px-2 py-1 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/10"
                      >
                        <Flag className="h-2.5 w-2.5" />
                        Flag
                      </button>
                      {job.status === "published" && (
                        <button
                          type="button"
                          onClick={() => takeDownJob(job.id, job.title)}
                          disabled={takedownBusyId === job.id}
                          className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-300 hover:border-rose-500/40 hover:text-rose-300 disabled:opacity-40"
                        >
                          {takedownBusyId === job.id ? (
                            <Loader2 className="h-2.5 w-2.5 animate-spin" />
                          ) : (
                            <UserX className="h-2.5 w-2.5" />
                          )}
                          Take down
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <Building2 className="h-4 w-4 text-amber-400" />
                  Suspicious employers
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Accounts that post without hiring, burst-publish, or carry flagged listings.
                </p>
              </div>
              <span className="text-[11px] text-zinc-500">
                {suspiciousEmployers ? `${suspiciousEmployers.length} flagged by heuristics` : "Scanning…"}
              </span>
            </div>

            <div className="mt-4 space-y-2">
              {suspiciousLoading && !suspiciousEmployers ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : !suspiciousEmployers || suspiciousEmployers.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  No employers above the risk threshold.
                </div>
              ) : (
                suspiciousEmployers.map((company) => (
                  <div
                    key={company.id}
                    className="rounded-xl border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ${riskTone(company.risk_score)}`}
                      >
                        <ShieldAlert className="h-3 w-3" />
                        risk {company.risk_score}
                      </span>
                      <span className="font-semibold text-zinc-100">{company.name}</span>
                      {company.is_verified && (
                        <BadgeCheck className="h-3.5 w-3.5 text-emerald-400" />
                      )}
                      <span className="ml-auto text-[10px] text-zinc-500">
                        {fmt(company.postings.published)} live · {fmt(company.applications)} applicants ·{" "}
                        {fmt(company.hires)} hires
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-zinc-500">
                      owner {company.owner.email} ·{" "}
                      {relativeTime(company.owner.last_active_at)}
                    </p>
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {company.risk_reasons.map((reason) => (
                        <li
                          key={reason}
                          className="rounded bg-zinc-800/70 px-1.5 py-0.5 text-[10px] text-zinc-400"
                        >
                          {reason}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => toggleEmployerVerified(company)}
                        disabled={empBusyId === company.id}
                        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-semibold disabled:opacity-40 ${
                          company.is_verified
                            ? "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
                            : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10"
                        }`}
                      >
                        {empBusyId === company.id ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        ) : (
                          <BadgeCheck className="h-2.5 w-2.5" />
                        )}
                        {company.is_verified ? "Unverify" : "Verify"}
                      </button>
                      <button
                        type="button"
                        onClick={() => openFlagDialog("company", company.id, company.name)}
                        className="inline-flex items-center gap-1 rounded border border-rose-500/30 px-2 py-1 text-[10px] font-semibold text-rose-300 hover:bg-rose-500/10"
                      >
                        <Flag className="h-2.5 w-2.5" />
                        Flag employer
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleEmployerOwner(company)}
                        disabled={ownerBusyId === company.id}
                        className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-semibold disabled:opacity-40 ${
                          company.owner.is_active
                            ? "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
                            : "border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10"
                        }`}
                      >
                        {ownerBusyId === company.id ? (
                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        ) : (
                          <UserX className="h-2.5 w-2.5" />
                        )}
                        {company.owner.is_active ? "Suspend owner" : "Reinstate owner"}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}

      {/* ---------------- AI & Ops ---------------- */}
      {activeTab === "ops" && (
        <div className="mt-6 space-y-6">
          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                <Sparkles className="h-4 w-4 text-teal-400" />
                LLM usage &amp; cost meter
              </h2>
              <span
                className={`self-start rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${
                  usage?.llm_enabled
                    ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                    : "bg-amber-500/10 text-amber-300 ring-amber-500/30"
                }`}
              >
                {usage?.llm_enabled ? "LLM enabled" : "KILL SWITCH ACTIVE"}
              </span>
            </div>

            {!usage ? (
              <div className="flex items-center justify-center py-10 text-zinc-500">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : (
              <>
                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {[
                    { label: "Calls", value: fmt(usage.totals.calls) },
                    { label: "Prompt tokens", value: fmt(usage.totals.prompt_tokens) },
                    { label: "Completion tokens", value: fmt(usage.totals.completion_tokens) },
                    { label: "Cache hits", value: fmt(usage.totals.cache_hits) },
                    {
                      label: "Est. cost",
                      value:
                        usage.totals.estimated_cost_usd === null
                          ? "n/a"
                          : `$${usage.totals.estimated_cost_usd.toFixed(4)}`,
                    },
                  ].map((tile) => (
                    <div key={tile.label} className="rounded-lg bg-zinc-950/60 p-3">
                      <p className="text-[10px] uppercase tracking-wider text-zinc-500">
                        {tile.label}
                      </p>
                      <p className="mt-1 text-sm font-bold text-zinc-100">{tile.value}</p>
                    </div>
                  ))}
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                  <Terminal className="h-3.5 w-3.5" />
                  Kill switch: <code className="text-amber-300">{config?.llm.kill_switch ?? "LLM_ENABLED=false"}</code>
                  <span>·</span> provider {config?.llm.provider ?? "—"} / {config?.llm.model ?? "—"}
                  <span>·</span> key {config?.llm.has_api_key ? "present" : "absent (fallbacks active)"}
                  <span>·</span> avg latency {Math.round(usage.totals.avg_latency_ms)} ms
                </div>

                {usage.by_route.length === 0 ? (
                  <p className="mt-4 text-xs text-zinc-500">
                    No LLM calls recorded yet — every route is on its deterministic fallback.
                  </p>
                ) : (
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[560px] text-left text-xs">
                      <thead>
                        <tr className="text-zinc-500">
                          <th className="pb-2 font-medium">Route</th>
                          <th className="pb-2 font-medium">Calls</th>
                          <th className="pb-2 font-medium">Tokens</th>
                          <th className="pb-2 font-medium">Avg ms</th>
                          <th className="pb-2 text-right font-medium">Flagged</th>
                        </tr>
                      </thead>
                      <tbody className="text-zinc-300">
                        {usage.by_route.map((route) => (
                          <tr key={route.route} className="border-t border-zinc-800/60">
                            <td className="py-1.5 pr-4 font-mono text-[11px] text-zinc-300">
                              {route.route}
                            </td>
                            <td className="py-1.5 pr-4">{fmt(route.calls)}</td>
                            <td className="py-1.5 pr-4">
                              {fmt(route.prompt_tokens + route.completion_tokens)}
                            </td>
                            <td className="py-1.5 pr-4">{Math.round(route.avg_latency_ms)}</td>
                            <td className={`py-1.5 text-right ${route.flagged ? "text-amber-400" : ""}`}>
                              {fmt(route.flagged)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {usage.recent.length > 0 && (
                  <details className="mt-4 rounded-lg border border-zinc-800/70 bg-zinc-950/40 p-3">
                    <summary className="cursor-pointer text-[11px] font-semibold text-zinc-400">
                      Recent calls ({usage.recent.length})
                    </summary>
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full min-w-[640px] text-left text-[11px]">
                        <thead>
                          <tr className="text-zinc-500">
                            <th className="pb-1 font-medium">When</th>
                            <th className="pb-1 font-medium">Route</th>
                            <th className="pb-1 font-medium">Model</th>
                            <th className="pb-1 font-medium">Tokens</th>
                            <th className="pb-1 font-medium">Latency</th>
                            <th className="pb-1 text-right font-medium">Flags</th>
                          </tr>
                        </thead>
                        <tbody className="text-zinc-400">
                          {usage.recent.map((call) => (
                            <tr key={call.id} className="border-t border-zinc-800/50">
                              <td className="py-1 pr-3">{formatDateTime(call.created_at)}</td>
                              <td className="py-1 pr-3 font-mono">{call.route}</td>
                              <td className="py-1 pr-3">{call.model}</td>
                              <td className="py-1 pr-3">
                                {fmt(call.prompt_tokens + call.completion_tokens)}
                              </td>
                              <td className="py-1 pr-3">{call.latency_ms} ms</td>
                              <td className="py-1 text-right">
                                {call.cached && <span className="mr-1 text-teal-400">cached</span>}
                                {call.flagged && <span className="text-amber-400">flagged</span>}
                                {!call.cached && !call.flagged && "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                )}
              </>
            )}
          </section>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <Copy className="h-4 w-4 text-teal-400" />
                  Duplicate jobs
                </h2>
                <button
                  type="button"
                  onClick={scanDuplicates}
                  disabled={duplicatesLoading}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-50"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${duplicatesLoading ? "animate-spin" : ""}`} />
                  Scan
                </button>
              </div>
              <p className="mt-2 text-[11px] text-zinc-500">
                Cosine ≥ 0.92 + title similarity ≥ 0.60. Detection only — retire a duplicate from
                the Moderation tab after review.
              </p>
              {!duplicates ? (
                <p className="mt-4 text-xs text-zinc-500">
                  Run a scan to inspect candidate duplicate pairs.
                </p>
              ) : duplicates.pairs.length === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  No candidate pairs among {fmt(duplicates.jobs_examined)} embedded jobs.
                </p>
              ) : (
                <div className="mt-4 space-y-3">
                  {duplicates.pairs.map((pair) => (
                    <div
                      key={`${pair.job_a.id}-${pair.job_b.id}`}
                      className="rounded-lg border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-zinc-200">
                          {pair.job_a.title} ↔ {pair.job_b.title}
                        </span>
                        <span className="font-mono text-amber-300">
                          cos {pair.cosine} · title {pair.title_similarity}
                        </span>
                      </div>
                      <p className="mt-1 text-[11px] text-zinc-500">
                        keep → {pair.suggested_survivor_id.slice(0, 8)} · retire →{" "}
                        {pair.suggested_retire_id.slice(0, 8)}
                      </p>
                      <div className="mt-2 flex gap-2">
                        <Link
                          href={`/jobs/${pair.job_a.id}`}
                          className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
                        >
                          Open A
                          <ArrowUpRight className="h-3 w-3" />
                        </Link>
                        <Link
                          href={`/jobs/${pair.job_b.id}`}
                          className="inline-flex items-center gap-1 rounded border border-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
                        >
                          Open B
                          <ArrowUpRight className="h-3 w-3" />
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
              <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <AlertTriangle className="h-4 w-4 text-amber-400" />
                  Parse failures
                </h2>
                <span className="text-[11px] text-zinc-500">
                  stuck after {failures?.stuck_after_minutes ?? 15} min
                </span>
              </div>
              {!failures ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : failures.items.length === 0 ? (
                <p className="mt-4 text-xs text-zinc-500">
                  No failed or stuck résumé parses.
                </p>
              ) : (
                <ul className="mt-4 space-y-2">
                  {failures.items.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800/70 bg-zinc-950/50 px-3 py-2 text-xs"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-zinc-200">
                          {item.original_filename || item.id.slice(0, 8)}{" "}
                          <span
                            className={
                              item.parse_status === "failed" ? "text-rose-400" : "text-amber-400"
                            }
                          >
                            ({item.parse_status}
                            {item.stuck ? ", stuck" : ""})
                          </span>
                        </p>
                        <p className="font-mono text-[10px] text-zinc-600">
                          profile {item.profile_id.slice(0, 8)} · {formatDateTime(item.created_at)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRetry(item.id)}
                        disabled={retryingId === item.id}
                        className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-50"
                      >
                        {retryingId === item.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3 w-3" />
                        )}
                        Retry
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                  <GitMerge className="h-4 w-4 text-teal-400" />
                  Skill merge
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  Re-points profiles, jobs, aliases, edges and affinities in one transaction,
                  then refreshes the survivor embedding.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSkillReload((n) => n + 1)}
                disabled={skillsLoading}
                className="inline-flex items-center gap-1.5 self-start rounded-lg border border-zinc-800 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300 disabled:opacity-50"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${skillsLoading ? "animate-spin" : ""}`} />
                Reload
              </button>
            </div>

            <form onSubmit={submitSkillSearch} className="mt-4 flex flex-col gap-2 sm:flex-row">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
                <input
                  value={skillInput}
                  onChange={(e) => setSkillInput(e.target.value)}
                  placeholder="Search skills (e.g. Node, React)…"
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none"
                />
              </div>
              <button
                type="submit"
                className="rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs font-semibold text-zinc-300 hover:border-teal-500/40 hover:text-teal-300"
              >
                Search
              </button>
            </form>

            {skills && (
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block text-xs text-zinc-400">
                  Source (absorbed &amp; removed)
                  <select
                    value={sourceId}
                    onChange={(e) => setSourceId(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
                  >
                    <option value="">— pick source skill —</option>
                    {skills.items.map((skill) => (
                      <option key={skill.id} value={skill.id}>
                        {skill.name} · {skill.profiles} profiles / {skill.jobs} jobs
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-zinc-400">
                  Target (canonical survivor)
                  <select
                    value={targetId}
                    onChange={(e) => setTargetId(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-200 focus:border-teal-500 focus:outline-none"
                  >
                    <option value="">— pick target skill —</option>
                    {skills.items.map((skill) => (
                      <option key={skill.id} value={skill.id}>
                        {skill.name} · {skill.profiles} profiles / {skill.jobs} jobs
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-[11px] text-zinc-500">
                {skills
                  ? `${fmt(skills.total_skills)} skills total · showing ${skills.items.length}`
                  : "Loading skill inventory…"}
              </p>
              <button
                type="button"
                onClick={handleMerge}
                disabled={!sourceId || !targetId || sourceId === targetId || mergeBusy}
                className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-400 disabled:opacity-50"
              >
                {mergeBusy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <GitMerge className="h-3.5 w-3.5" />
                )}
                Merge into target
              </button>
            </div>

            {mergeReport && (
              <div className="mt-4 rounded-xl border border-teal-500/25 bg-teal-500/5 p-4 text-xs text-teal-300">
                <p className="font-semibold">
                  Merged “{mergeReport.source.name}” → “{mergeReport.target.name}” · embedding{" "}
                  {mergeReport.embedding_refreshed ? "refreshed" : "kept"}
                </p>
                <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-[11px] sm:grid-cols-5">
                  <span>profiles +{mergeReport.profile_skills.moved} / −{mergeReport.profile_skills.deduped ?? 0}</span>
                  <span>jobs +{mergeReport.job_skills.moved} / −{mergeReport.job_skills.deduped ?? 0}</span>
                  <span>aliases +{mergeReport.skill_aliases.moved}</span>
                  <span>edges +{mergeReport.skill_edges.moved}</span>
                  <span>affinities +{mergeReport.skill_affinities.moved}</span>
                </div>
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-200">Skill inventory</h3>
              <span className="text-[11px] text-zinc-500">
                {skills ? `${fmt(skills.total_skills)} canonical skills` : "Loading…"}
              </span>
            </div>
            <div className="mt-4 overflow-x-auto">
              {!skills ? (
                <div className="flex items-center justify-center py-10 text-zinc-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : skills.items.length === 0 ? (
                <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-xs text-zinc-500">
                  No skills match “{skillQuery}”.
                </div>
              ) : (
                <table className={`w-full min-w-[640px] text-left text-xs ${skillsLoading ? "opacity-60" : ""}`}>
                  <thead>
                    <tr className="text-zinc-500">
                      <th className="pb-2 font-medium">Skill</th>
                      <th className="pb-2 font-medium">Category</th>
                      <th className="pb-2 font-medium">Profiles</th>
                      <th className="pb-2 font-medium">Jobs</th>
                      <th className="pb-2 font-medium">Aliases</th>
                      <th className="pb-2 text-right font-medium">Embedding</th>
                    </tr>
                  </thead>
                  <tbody className="text-zinc-300">
                    {skills.items.map((skill) => (
                      <tr key={skill.id} className="border-t border-zinc-800/60">
                        <td className="py-2 pr-4 font-semibold text-zinc-100">{skill.name}</td>
                        <td className="py-2 pr-4 text-[11px] text-zinc-500">
                          {skill.category || "—"}
                        </td>
                        <td className="py-2 pr-4 font-mono">{fmt(skill.profiles)}</td>
                        <td className="py-2 pr-4 font-mono">{fmt(skill.jobs)}</td>
                        <td className="py-2 pr-4 font-mono">{fmt(skill.aliases)}</td>
                        <td className="py-2 text-right text-[11px]">
                          {skill.has_embedding ? (
                            <span className="text-teal-400">ready</span>
                          ) : (
                            <span className="text-amber-400">missing</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </div>
      )}

      {/* ---------------- Weights & Models ---------------- */}
      {activeTab === "config" && (
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                <Wrench className="h-4 w-4 text-teal-400" />
                Scoring weights
              </h2>
              <span className="rounded-full bg-zinc-800 px-2.5 py-0.5 text-[11px] font-semibold text-zinc-300">
                source: {config?.source ?? "—"}
              </span>
            </div>

            {!config ? (
              <div className="flex items-center justify-center py-10 text-zinc-500">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : (
              <>
                <div className="mt-4 space-y-2.5">
                  {config.weights.map((weight) => (
                    <div key={weight.component} className="flex items-center justify-between gap-3">
                      <span className="text-xs text-zinc-300">{weight.label}</span>
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          step={0.01}
                          min={0}
                          value={editWeights[weight.component] ?? 0}
                          onChange={(e) =>
                            setEditWeights((prev) => ({
                              ...prev,
                              [weight.component]: parseFloat(e.target.value),
                            }))
                          }
                          className="w-20 rounded-lg border border-zinc-800 bg-zinc-950/70 px-2 py-1 text-right font-mono text-xs text-zinc-200 focus:border-teal-500 focus:outline-none"
                          aria-label={`${weight.label} weight`}
                        />
                        <span className="w-12 text-right text-[10px] text-zinc-600">
                          def {weight.default}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-4 flex items-center justify-between">
                  <span
                    className={`text-xs font-semibold ${
                      sumValid ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    Σw = {weightSum.toFixed(4)} {sumValid ? "✓" : "— must equal 1.0000"}
                  </span>
                  <button
                    type="button"
                    onClick={handleSaveConfig}
                    disabled={!sumValid || configBusy}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500 px-4 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-50"
                  >
                    {configBusy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="h-3.5 w-3.5" />
                    )}
                    Save weights
                  </button>
                </div>
                <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
                  M4 bounds track this baseline: each feedback step stays within [
                  {config.m4.bounds[0]}×, {config.m4.bounds[1]}×] with η=
                  {config.m4.learning_rate} and shrinkage n/(n+{config.m4.shrinkage_k}).
                </p>
              </>
            )}
          </section>

          <section className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-zinc-300">
                <Database className="h-4 w-4 text-teal-400" />
                Model registry
              </h2>
              <span className="text-[11px] text-zinc-500">{models.length} artifacts</span>
            </div>
            {models.length === 0 ? (
              <p className="mt-4 text-xs text-zinc-500">
                No artifacts registered yet — run{" "}
                <code className="text-teal-300">python ml/train.py</code> to train and register
                M1–M3.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {models.map((model) => (
                  <div
                    key={model.id}
                    className="rounded-lg border border-zinc-800/70 bg-zinc-950/50 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-semibold text-zinc-100">{model.name}</span>
                      <span className="font-mono text-[10px] text-zinc-500">{model.version}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px]">
                      <span className={model.active ? "text-emerald-400" : "text-zinc-500"}>
                        {model.active ? "● active" : "○ staged"}
                      </span>
                      <span className={model.artifact_exists ? "text-teal-400" : "text-amber-400"}>
                        {model.artifact_exists ? "artifact on disk" : "artifact missing"}
                      </span>
                      <span className="text-zinc-600">
                        trained {formatDate(model.trained_at)}
                      </span>
                    </div>
                    <p className="mt-1 break-all font-mono text-[10px] text-zinc-600">
                      {Object.entries(model.metrics)
                        .map(
                          ([key, value]) =>
                            `${key}=${typeof value === "number" ? value.toFixed(4) : String(value)}`,
                        )
                        .join(" · ") || "no metrics"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {flagTarget && (
        <FlagDialog
          target={flagTarget}
          reason={flagReason}
          severity={flagSeverity}
          details={flagDetails}
          busy={flagSubmitting}
          onReason={setFlagReason}
          onSeverity={setFlagSeverity}
          onDetails={setFlagDetails}
          onCancel={() => setFlagTarget(null)}
          onSubmit={submitFlag}
        />
      )}

      <div className="mt-8 flex items-center justify-center gap-4">
        <Link
          href="/dashboard"
          className="text-xs font-semibold text-zinc-500 hover:text-zinc-300"
        >
          ← Back to dashboard
        </Link>
        <span className="text-zinc-800">|</span>
        <span className="inline-flex items-center gap-1 text-[11px] text-zinc-600">
          <ShieldCheck className="h-3 w-3" />
          Admin-only surface · role-gated on every request
        </span>
      </div>
    </div>
  );
}
