"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  ArrowRight,
  Briefcase,
  Building2,
  Check,
  Lock,
  Mail,
  User as UserIcon,
} from "lucide-react";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();

  const [role, setRole] = useState<"job_seeker" | "employer">("job_seeker");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    if (role === "employer" && !companyName.trim()) {
      setError("Please enter your company name.");
      return;
    }

    setIsSubmitting(true);

    try {
      await register({
        email,
        password,
        role,
        first_name: firstName.trim() || undefined,
        last_name: lastName.trim() || undefined,
        company_name: role === "employer" ? companyName.trim() : undefined,
      });
      router.push(role === "job_seeker" ? "/onboarding" : "/dashboard");
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("An unexpected registration error occurred.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-lg space-y-8 rounded-2xl border border-zinc-800/80 bg-zinc-900/50 p-8 backdrop-blur-xl shadow-2xl shadow-black/40">
        <div className="text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-teal-500/10 text-teal-400 ring-1 ring-teal-500/30">
            <Briefcase className="h-6 w-6" />
          </div>
          <h2 className="mt-4 text-2xl font-bold tracking-tight text-white">
            Create your account
          </h2>
          <p className="mt-1.5 text-sm text-zinc-400">
            Join the next-generation AI recommendation platform
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3.5 text-sm text-rose-300">
            {error}
          </div>
        )}

        {/* Role Selector */}
        <div className="space-y-2">
          <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400">
            I am joining as a
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setRole("job_seeker")}
              className={`relative flex flex-col items-start rounded-xl border p-4 text-left transition-all ${
                role === "job_seeker"
                  ? "border-teal-500/80 bg-teal-500/10 text-white shadow-sm ring-1 ring-teal-500/40"
                  : "border-zinc-800 bg-zinc-950/40 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              }`}
            >
              <div className="flex w-full items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-500/20 text-teal-300">
                  <UserIcon className="h-4 w-4" />
                </span>
                {role === "job_seeker" && (
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-teal-400 text-zinc-950">
                    <Check className="h-3 w-3 stroke-[3]" />
                  </span>
                )}
              </div>
              <p className="mt-3 font-semibold text-sm text-white">Job Seeker</p>
              <p className="mt-0.5 text-xs text-zinc-400">
                Discover AI-matched roles and track applications
              </p>
            </button>

            <button
              type="button"
              onClick={() => setRole("employer")}
              className={`relative flex flex-col items-start rounded-xl border p-4 text-left transition-all ${
                role === "employer"
                  ? "border-indigo-500/80 bg-indigo-500/10 text-white shadow-sm ring-1 ring-indigo-500/40"
                  : "border-zinc-800 bg-zinc-950/40 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
              }`}
            >
              <div className="flex w-full items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/20 text-indigo-300">
                  <Building2 className="h-4 w-4" />
                </span>
                {role === "employer" && (
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-400 text-zinc-950">
                    <Check className="h-3 w-3 stroke-[3]" />
                  </span>
                )}
              </div>
              <p className="mt-3 font-semibold text-sm text-white">Employer</p>
              <p className="mt-0.5 text-xs text-zinc-400">
                Post positions and get ranked candidate recommendations
              </p>
            </button>
          </div>
        </div>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                First name
              </label>
              <input
                type="text"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="Aanya"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 transition-colors"
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
                placeholder="Sharma"
                className="mt-1.5 block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 px-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 transition-colors"
              />
            </div>
          </div>

          {role === "employer" && (
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
                Company Name *
              </label>
              <div className="relative mt-1.5 rounded-lg shadow-sm">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
                  <Building2 className="h-4 w-4" />
                </div>
                <input
                  type="text"
                  required
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Acme AI Technologies"
                  className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 transition-colors"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Email address *
            </label>
            <div className="relative mt-1.5 rounded-lg shadow-sm">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
                <Mail className="h-4 w-4" />
              </div>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 transition-colors"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-zinc-400">
              Password (min 8 characters) *
            </label>
            <div className="relative mt-1.5 rounded-lg shadow-sm">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-zinc-500">
                <Lock className="h-4 w-4" />
              </div>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="block w-full rounded-lg border border-zinc-800 bg-zinc-950/70 py-2.5 pl-9 pr-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500 transition-colors"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="group relative flex w-full justify-center items-center gap-2 rounded-lg bg-teal-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 shadow-md shadow-teal-500/20 hover:bg-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400 disabled:opacity-50 active:scale-[0.99] transition-all"
          >
            {isSubmitting ? (
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-950 border-t-transparent" />
            ) : (
              <>
                Create Account
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </>
            )}
          </button>
        </form>

        <p className="text-center text-xs text-zinc-400">
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium text-teal-400 hover:text-teal-300 underline-offset-4 hover:underline"
          >
            Sign in here
          </Link>
        </p>
      </div>
    </div>
  );
}
