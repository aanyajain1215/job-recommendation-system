"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import {
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import { NotificationItem } from "@/lib/types";
import { Bell, BellRing, CheckCheck, ExternalLink, Sparkles } from "lucide-react";

export default function NotificationsPage() {
  const router = useRouter();
  const { user, token, isLoading: authLoading } = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setError(null);
      const result = await getNotifications(token, { limit: 50 });
      setItems(result.items);
      setUnread(result.unread);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load notifications");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
      return;
    }
    if (token && user) load();
  }, [user, token, authLoading, router, load]);

  const handleOpen = async (item: NotificationItem) => {
    if (!token) return;
    if (item.read_at === null) {
      try {
        await markNotificationRead(item.id, token);
        setItems((prev) =>
          prev.map((n) =>
            n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n,
          ),
        );
        setUnread((prev) => Math.max(0, prev - 1));
      } catch {
        // Non-blocking: still navigate to the alert target.
      }
    }
    router.push(item.link || "/recommendations");
  };

  const handleMarkAll = async () => {
    if (!token || unread === 0) return;
    setBusy(true);
    try {
      await markAllNotificationsRead(token);
      const now = new Date().toISOString();
      setItems((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? now })));
      setUnread(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to mark notifications read");
    } finally {
      setBusy(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-zinc-800/80 pb-6">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-400">
            <BellRing className="h-4 w-4" />
            Job alerts
          </div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">Notifications</h1>
          <p className="mt-1 text-sm text-zinc-400">
            New roles that match the jobs you saved. {unread > 0 ? `${unread} unread.` : "You're all caught up."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/settings"
            className="rounded-lg border border-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:border-zinc-700 hover:text-white"
          >
            Alert settings
          </Link>
          <button
            type="button"
            onClick={handleMarkAll}
            disabled={busy || unread === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-teal-500 px-3 py-1.5 text-xs font-semibold text-zinc-950 hover:bg-teal-400 disabled:opacity-40"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            Mark all read
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-6 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {error}
        </div>
      )}

      <div className="mt-6 space-y-3">
        {items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-12 text-center">
            <Bell className="mx-auto mb-3 h-10 w-10 text-zinc-600" />
            <h3 className="text-lg font-semibold text-zinc-200">No alerts yet</h3>
            <p className="mt-1 text-sm text-zinc-400">
              Save a few jobs you like and we&apos;ll tell you when similar roles go live.
            </p>
            <Link
              href="/saved"
              className="mt-4 inline-block rounded-lg bg-teal-500 px-4 py-2 text-xs font-semibold text-zinc-950 hover:bg-teal-400"
            >
              View saved jobs
            </Link>
          </div>
        ) : (
          items.map((item) => {
            const isUnread = item.read_at === null;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => handleOpen(item)}
                className={`flex w-full items-start gap-3 rounded-xl border p-4 text-left transition-colors ${
                  isUnread
                    ? "border-teal-500/30 bg-teal-500/5 hover:border-teal-500/50"
                    : "border-zinc-800/80 bg-zinc-900/40 hover:border-zinc-700"
                }`}
              >
                <span
                  className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                    isUnread ? "bg-teal-500/15 text-teal-300" : "bg-zinc-800/70 text-zinc-500"
                  }`}
                >
                  <Sparkles className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span
                      className={`truncate text-sm font-semibold ${
                        isUnread ? "text-white" : "text-zinc-300"
                      }`}
                    >
                      {item.title}
                    </span>
                    {isUnread && (
                      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal-400" />
                    )}
                  </span>
                  {item.body && (
                    <span className="mt-1 block text-xs leading-relaxed text-zinc-400">
                      {item.body}
                    </span>
                  )}
                  <span className="mt-1.5 block text-[11px] text-zinc-500">
                    {new Date(item.created_at).toLocaleString()}
                  </span>
                </span>
                <ExternalLink className="mt-1 h-3.5 w-3.5 flex-shrink-0 text-zinc-600" />
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
