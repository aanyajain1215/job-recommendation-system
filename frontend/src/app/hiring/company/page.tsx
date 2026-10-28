"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { createMyCompany, getMyCompany, updateMyCompany } from "@/lib/api";
import { CompanyDetail } from "@/lib/types";
import { EmployerLoading, useEmployerAuth } from "@/lib/use-employer-auth";
import { AlertTriangle, Building2, ExternalLink, Eye, Globe, MapPin, Save } from "lucide-react";

/** The API returns a plain-string detail; this is how we detect "no company". */
const NO_COMPANY = "No company profile is associated";

const INDUSTRY_HINTS = [
  "fintech",
  "healthtech",
  "saas",
  "edtech",
  "e-commerce",
  "consulting",
  "staffing",
  "ai/ml",
];

const SIZE_OPTIONS = ["1-10", "11-50", "51-200", "201-1000", "1000+"];

export default function CompanyProfilePage() {
  const { token, ready, isLoading: authLoading } = useEmployerAuth();

  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [company, setCompany] = useState<CompanyDetail | null>(null);

  // form
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [website, setWebsite] = useState("");
  const [location, setLocation] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [industry, setIndustry] = useState("");
  const [companySize, setCompanySize] = useState("");

  useEffect(() => {
    if (!ready || !token) return;
    getMyCompany(token)
      .then((c) => {
        setCompany(c);
        setName(c.name);
        setDescription(c.description ?? "");
        setWebsite(c.website ?? "");
        setLocation(c.location ?? "");
        setLogoUrl(c.logo_url ?? "");
        setIndustry(c.industry ?? "");
        setCompanySize(c.company_size ?? "");
      })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "Failed to load";
        if (msg.includes(NO_COMPANY)) setMissing(true);
        else setError(msg);
      })
      .finally(() => setLoading(false));
  }, [ready, token]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!token) return;
    if (!name.trim()) {
      setError("Company name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        description,
        website,
        location,
        logo_url: logoUrl,
        industry,
        company_size: companySize,
      };
      const saved = company
        ? await updateMyCompany(payload, token)
        : await createMyCompany({ name: name.trim() }, token).then((c) =>
            // creation only takes a name; follow up with the full profile
            updateMyCompany({ ...payload, name: c.name }, token),
          );
      setCompany(saved);
      setMissing(false);
      toast.success("Company profile saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  if (authLoading || !ready || loading) return <EmployerLoading />;

  const inputCls =
    "mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none";
  const labelCls = "block text-xs font-medium uppercase tracking-wider text-zinc-400";

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
          <Building2 className="h-4 w-4" />
          Company
        </div>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-100">
          Company profile
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          This is what job seekers see on your postings.
        </p>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {missing && (
        <div className="mt-6 flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
          Your account doesn&apos;t have a company profile yet — create one below so your postings
          show a company name.
        </div>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-3">
        {/* Editor */}
        <form onSubmit={onSubmit} className="lg:col-span-2">
          <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-6">
            <div>
              <label className={labelCls}>Company name *</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
                placeholder="e.g. TechNova Labs"
                required
                minLength={2}
              />
            </div>

            <div className="mt-5">
              <label className={labelCls}>About the company</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={5}
                className={inputCls}
                placeholder="What does your company do? Mission, stack, culture…"
              />
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className={labelCls}>Website</label>
                <input
                  value={website}
                  onChange={(e) => setWebsite(e.target.value)}
                  className={inputCls}
                  placeholder="https://example.com"
                />
              </div>
              <div>
                <label className={labelCls}>Location</label>
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  className={inputCls}
                  placeholder="e.g. Bengaluru, India"
                />
              </div>
            </div>

            <div className="mt-5">
              <label className={labelCls}>Logo URL</label>
              <input
                value={logoUrl}
                onChange={(e) => setLogoUrl(e.target.value)}
                className={inputCls}
                placeholder="https://…/logo.png"
              />
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className={labelCls}>Industry</label>
                <input
                  value={industry}
                  onChange={(e) => setIndustry(e.target.value)}
                  list="industry-hints"
                  className={inputCls}
                  placeholder="e.g. fintech"
                />
                <datalist id="industry-hints">
                  {INDUSTRY_HINTS.map((i) => (
                    <option key={i} value={i} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className={labelCls}>Company size</label>
                <select
                  value={companySize}
                  onChange={(e) => setCompanySize(e.target.value)}
                  className={inputCls}
                >
                  <option value="">Prefer not to say</option>
                  {SIZE_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s} employees
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 flex items-center gap-3 border-t border-zinc-800/70 pt-5">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-6 py-3 text-sm font-semibold text-zinc-950 shadow-lg shadow-teal-500/25 hover:bg-teal-400 active:scale-[0.98] transition-all disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {saving ? "Saving…" : "Save profile"}
              </button>
            </div>
          </div>
        </form>

        {/* Live preview */}
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Preview
          </h2>
          <div className="mt-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-5">
            <div className="flex items-center gap-3">
              {logoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoUrl}
                  alt={`${name || "Company"} logo`}
                  className="h-12 w-12 rounded-lg border border-zinc-800 object-cover"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.display = "none";
                  }}
                />
              ) : (
                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-gradient-to-br from-teal-400/80 to-cyan-600/80 text-zinc-950">
                  <Building2 className="h-6 w-6" />
                </div>
              )}
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-semibold text-zinc-100">
                    {name || "Your company"}
                  </span>
                  {company?.is_verified && (
                    <span className="rounded-full bg-teal-500/10 px-2 py-0.5 text-[10px] font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30">
                      Verified
                    </span>
                  )}
                </div>
                {industry && <div className="text-xs text-zinc-500">{industry}</div>}
              </div>
            </div>

            {description && (
              <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
                {description}
              </p>
            )}

            <div className="mt-4 space-y-1.5 text-xs text-zinc-400">
              {location && (
                <div className="flex items-center gap-1.5">
                  <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                  {location}
                </div>
              )}
              {website && (
                <div className="flex items-center gap-1.5">
                  <Globe className="h-3.5 w-3.5 text-zinc-500" />
                  <a
                    href={website}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-teal-400"
                  >
                    {website}
                  </a>
                </div>
              )}
              {companySize && (
                <div className="flex items-center gap-1.5">
                  <Eye className="h-3.5 w-3.5 text-zinc-500" />
                  {companySize} employees
                </div>
              )}
            </div>

            {company && (
              <div className="mt-4 border-t border-zinc-800/70 pt-3 text-[11px] text-zinc-500">
                <div>
                  Slug: <code className="text-zinc-400">{company.slug}</code>
                </div>
                <div className="mt-0.5">
                  Open postings:{" "}
                  <span className="font-semibold text-teal-300">{company.open_postings}</span>
                </div>
              </div>
            )}
          </div>

          <Link
            href="/hiring/postings"
            className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-teal-400 hover:text-teal-300"
          >
            Manage your postings
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </div>
  );
}
