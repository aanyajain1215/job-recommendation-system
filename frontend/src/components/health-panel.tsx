"use client";

import { useState } from "react";

import {
  fetchReadiness,
  getBrowserApiBaseUrl,
  type HealthResult,
} from "@/lib/api";

type HealthPanelProps = {
  initial: HealthResult;
};

function StatusBadge({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
        ok
          ? "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30"
          : "bg-red-500/15 text-red-400 ring-1 ring-red-500/30"
      }`}
    >
      {ok ? "Connected" : "Unavailable"}
    </span>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 border-b border-zinc-800/60 py-3 last:border-b-0">
      <dt className="text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
      <dd className="font-mono text-sm break-all text-zinc-200">{value}</dd>
    </div>
  );
}

export function HealthPanel({ initial }: HealthPanelProps) {
  const [result, setResult] = useState<HealthResult>(initial);
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function refreshFromBrowser() {
    setIsRefreshing(true);
    const next = await fetchReadiness(getBrowserApiBaseUrl());
    setResult(next);
    setIsRefreshing(false);
  }

  return (
    <section className="w-full max-w-2xl rounded-2xl border border-zinc-800/60 bg-zinc-900/70 p-6 shadow-2xl shadow-teal-950/40 backdrop-blur">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-teal-400">Foundation check</p>
          <h2 className="mt-1 text-xl font-semibold text-zinc-100">
            Frontend → API → Postgres
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            This page is served by Next.js, calls FastAPI, and reads a real
            row from PostgreSQL. No mocked data.
          </p>
        </div>
        <StatusBadge ok={result.ok} />
      </div>

      {result.ok ? (
        <dl>
          <Field label="Service" value={result.data.service} />
          <Field label="Database" value={result.data.database} />
          <Field label="Heartbeat message" value={result.data.heartbeat_message} />
          <Field label="Heartbeat id" value={result.data.heartbeat_id} />
          <Field
            label="Row recorded at"
            value={result.data.heartbeat_recorded_at}
          />
          <Field label="Database time" value={result.data.database_time} />
          <Field label="Postgres version" value={result.data.postgres_version} />
        </dl>
      ) : (
        <p className="rounded-lg bg-red-950/50 p-4 font-mono text-sm text-red-300">
          {result.error}
        </p>
      )}

      <button
        type="button"
        onClick={refreshFromBrowser}
        disabled={isRefreshing}
        className="mt-6 inline-flex items-center justify-center rounded-lg bg-teal-500 px-4 py-2.5 text-sm font-medium text-teal-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isRefreshing ? "Calling API…" : "Refresh from browser"}
      </button>
    </section>
  );
}
