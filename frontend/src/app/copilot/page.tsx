"use client";

import { FormEvent, KeyboardEvent, Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  Ban,
  Bot,
  Brain,
  CheckCircle2,
  ChevronDown,
  Info,
  Loader2,
  MessageSquare,
  PanelLeft,
  Plus,
  SendHorizontal,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Target,
  Trash2,
  User as UserIcon,
  WifiOff,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  addCopilotMemory,
  copilotChat,
  copilotDigest,
  deleteCopilotConversation,
  deleteCopilotMemory,
  getCopilotConversation,
  getCopilotConversations,
  getCopilotMemories,
  getCopilotStatus,
} from "@/lib/api";
import {
  CopilotCard,
  CopilotChatResponse,
  CopilotConversationSummary,
  CopilotMemory,
  CopilotMemoryKind,
  CopilotMessage,
  CopilotStatus,
  CopilotTrace,
} from "@/lib/types";
import { CopilotCards, knownCards } from "@/components/copilot-cards";

const MAX_MESSAGE = 2000;

const SUGGESTED_PROMPTS = [
  "What jobs fit me best right now?",
  "Find remote React jobs in Bangalore",
  "I want to switch to data science — what am I missing?",
  "Remember that I won't relocate outside Pune",
  "Show my saved jobs",
];

const MEMORY_KINDS: {
  kind: CopilotMemoryKind;
  label: string;
  icon: typeof SlidersHorizontal;
  tone: string;
}[] = [
  { kind: "preference", label: "Preferences", icon: SlidersHorizontal, tone: "text-teal-400" },
  { kind: "dealbreaker", label: "Dealbreakers", icon: Ban, tone: "text-rose-400" },
  { kind: "goal", label: "Goals", icon: Target, tone: "text-amber-400" },
  { kind: "fact", label: "Facts", icon: Info, tone: "text-sky-400" },
];

/** One chat bubble as the UI needs it (normalised from API messages and chat responses). */
type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  cards: CopilotCard[];
  trace: CopilotTrace[];
  memoriesUsed: string[];
  mode: "llm" | "fallback" | null;
  model: string | null;
};

/**
 * The conversation held in memory. `aliasOf` is the URL value it was started under
 * (null for a brand-new chat) so it stays visible while `?c=<new id>` propagates.
 */
type Thread = { id: string | null; aliasOf?: string | null; messages: UiMessage[] };

function fromApiMessage(m: CopilotMessage): UiMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    cards: knownCards(m.meta?.cards),
    trace: Array.isArray(m.meta?.trace) ? m.meta.trace : [],
    memoriesUsed: Array.isArray(m.meta?.memories_used) ? m.meta.memories_used : [],
    mode: m.meta?.mode ?? null,
    model: m.meta?.model ?? null,
  };
}

function fromChatResponse(r: CopilotChatResponse): UiMessage {
  return {
    id: r.message_id,
    role: "assistant",
    content: r.reply,
    cards: knownCards(r.cards),
    trace: Array.isArray(r.trace) ? r.trace : [],
    memoriesUsed: Array.isArray(r.memories_used) ? r.memories_used : [],
    mode: r.mode,
    model: r.model,
  };
}

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Push/replace `?c=<id>` without a navigation — Next syncs useSearchParams with the native History API. */
function setConversationInUrl(id: string | null, mode: "push" | "replace" = "push") {
  const url = id ? `/copilot?c=${encodeURIComponent(id)}` : "/copilot";
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

const currentUrlConversation = () =>
  new URLSearchParams(window.location.search).get("c");

// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: CopilotStatus | null }) {
  if (!status) {
    return <span className="h-5 w-28 animate-pulse rounded-full bg-zinc-800" />;
  }
  if (status.mode === "llm") {
    return (
      <span
        title={`${status.provider ?? "LLM"} · ${status.tools.length} tools available`}
        className="inline-flex items-center gap-1 rounded-full bg-teal-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-teal-300 ring-1 ring-inset ring-teal-500/30"
      >
        <Sparkles className="h-3 w-3" />
        AI · {status.model ?? status.provider ?? "LLM"}
      </span>
    );
  }
  return (
    <span
      title="No LLM is configured — the copilot answers with rule-based routing over the same tools."
      className="inline-flex items-center gap-1 rounded-full bg-zinc-800/80 px-2.5 py-0.5 text-[11px] font-semibold text-zinc-300 ring-1 ring-inset ring-zinc-700"
    >
      <WifiOff className="h-3 w-3" />
      Offline mode (rule-based)
    </span>
  );
}

function TraceRow({ trace, memoriesUsed }: { trace: CopilotTrace[]; memoriesUsed: string[] }) {
  if (trace.length === 0 && memoriesUsed.length === 0) return null;
  const wrote = trace.some((t) => t.writes && t.ok);
  return (
    <div className="mt-1.5 flex flex-wrap items-start gap-x-3 gap-y-1 pl-1 text-[11px] text-zinc-500">
      {trace.length > 0 && (
        <details className="group">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md px-1 py-0.5 transition-colors hover:bg-zinc-900 hover:text-zinc-300 [&::-webkit-details-marker]:hidden">
            <Wrench className="h-3 w-3" />
            {trace.length} tool{trace.length === 1 ? "" : "s"} used
            {wrote && <span className="text-amber-400/90">· changed your data</span>}
            <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
          </summary>
          <ul className="mt-1.5 space-y-1 rounded-lg border border-zinc-800/80 bg-zinc-900/60 p-2">
            {trace.map((t, i) => (
              <li key={`${t.tool}-${i}`} className="flex flex-wrap items-center gap-2">
                {t.ok ? (
                  <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="h-3 w-3 shrink-0 text-rose-400" />
                )}
                <code className="font-mono text-zinc-300">{t.tool}</code>
                <span className="tabular-nums text-zinc-500">{Math.round(t.ms)} ms</span>
                {t.writes && (
                  <span className="rounded bg-amber-500/10 px-1.5 py-px text-[10px] font-semibold text-amber-300 ring-1 ring-inset ring-amber-500/30">
                    changed your data
                  </span>
                )}
                {!t.ok && t.error && <span className="text-rose-300/90">{t.error}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {memoriesUsed.length > 0 && (
        <span
          title={memoriesUsed.join("\n")}
          className="inline-flex items-center gap-1 px-1 py-0.5 text-violet-300/80"
        >
          <Brain className="h-3 w-3" />
          used {memoriesUsed.length} memor{memoriesUsed.length === 1 ? "y" : "ies"}
        </span>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: UiMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-teal-500 px-4 py-2.5 text-sm leading-relaxed text-zinc-950 shadow-md shadow-teal-500/10 sm:max-w-[75%]">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950 shadow-md shadow-teal-500/10">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="inline-block max-w-full rounded-2xl rounded-tl-md border border-zinc-800/80 bg-zinc-900/70 px-4 py-2.5 text-sm leading-relaxed text-zinc-200 shadow-md sm:max-w-[85%]">
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
        <CopilotCards cards={message.cards} />
        <TraceRow trace={message.trace} memoriesUsed={message.memoriesUsed} />
      </div>
    </div>
  );
}

function TypingIndicator({ label }: { label: string }) {
  return (
    <div className="flex items-start gap-2.5" role="status" aria-live="polite">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950">
        <Bot className="h-4 w-4" />
      </div>
      <div className="rounded-2xl rounded-tl-md border border-zinc-800/80 bg-zinc-900/70 px-4 py-3">
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 animate-bounce rounded-full bg-teal-400 [animation-delay:-0.3s]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-teal-400 [animation-delay:-0.15s]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-teal-400" />
        </div>
        <p className="mt-1.5 text-[11px] text-zinc-500">{label}</p>
      </div>
    </div>
  );
}

function MemoryPanel({
  memories,
  error,
  onAdd,
  onDelete,
}: {
  memories: CopilotMemory[] | null;
  error: string | null;
  onAdd: (content: string, kind: CopilotMemoryKind) => Promise<boolean>;
  onDelete: (id: string) => void;
}) {
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<CopilotMemoryKind>("preference");
  const [saving, setSaving] = useState(false);
  const trimmed = content.trim();
  const valid = trimmed.length >= 4 && trimmed.length <= 240;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    const ok = await onAdd(trimmed, kind);
    setSaving(false);
    if (ok) setContent("");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="px-1 text-[11px] leading-relaxed text-zinc-500">
        The copilot remembers your preferences across chats. You&apos;re in control — delete
        anything, or add it yourself.
      </p>

      <form onSubmit={submit} className="mt-3 space-y-2 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-2.5">
        <div className="flex gap-2">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as CopilotMemoryKind)}
            aria-label="Memory type"
            className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1.5 text-xs text-zinc-200 focus:border-teal-500/60 focus:outline-none"
          >
            {MEMORY_KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label.replace(/s$/, "")}
              </option>
            ))}
          </select>
          <input
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={240}
            placeholder="e.g. Only full-time roles"
            aria-label="Memory text"
            className="min-w-0 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-teal-500/60 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          disabled={!valid || saving}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-teal-500/10 px-3 py-1.5 text-xs font-semibold text-teal-300 ring-1 ring-teal-500/30 transition-colors hover:bg-teal-500/20 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Remember this
        </button>
      </form>

      {error && (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-rose-400">
          <AlertCircle className="mt-px h-3 w-3 shrink-0" /> {error}
        </p>
      )}

      <div className="mt-3 min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {memories === null ? (
          <div className="flex items-center gap-2 px-1 text-xs text-zinc-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading memories…
          </div>
        ) : memories.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-center text-xs text-zinc-500">
            Nothing remembered yet. Tell the copilot things like &ldquo;Remember that I only want
            remote roles&rdquo;.
          </div>
        ) : (
          MEMORY_KINDS.map(({ kind: k, label, icon: Icon, tone }) => {
            const group = memories.filter((m) => m.kind === k);
            if (group.length === 0) return null;
            return (
              <section key={k}>
                <h4 className={`mb-1.5 flex items-center gap-1.5 px-1 text-[10px] font-semibold uppercase tracking-wider ${tone}`}>
                  <Icon className="h-3 w-3" /> {label}
                </h4>
                <ul className="space-y-1">
                  {group.map((m) => (
                    <li
                      key={m.id}
                      className="group flex items-start gap-2 rounded-lg border border-zinc-800/60 bg-zinc-900/40 px-2.5 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-xs text-zinc-200">{m.content}</p>
                        <p className="mt-0.5 text-[10px] text-zinc-500">
                          {m.source === "user" ? "added by you" : "learned in chat"} ·{" "}
                          {relativeTime(m.updated_at)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onDelete(m.id)}
                        title="Forget this"
                        aria-label={`Forget: ${m.content}`}
                        className="shrink-0 rounded p-1 text-zinc-500 transition-colors hover:bg-rose-500/10 hover:text-rose-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function CopilotView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const convId = searchParams.get("c");
  const { user, token, isLoading: authLoading } = useAuth();
  const isSeeker = user?.role === "job_seeker";

  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [conversations, setConversations] = useState<CopilotConversationSummary[] | null>(null);
  const [memories, setMemories] = useState<CopilotMemory[] | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [thread, setThread] = useState<Thread>({ id: null, messages: [] });
  const [threadError, setThreadError] = useState<{ id: string; message: string } | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<null | "chat" | "digest">(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [tab, setTab] = useState<"chats" | "memory">("chats");

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const localSeq = useRef(0);

  // Messages shown are derived: only the thread matching the URL is displayed.
  const threadId = thread.id;
  const showingThread =
    threadId === convId || (thread.aliasOf !== undefined && thread.aliasOf === convId);
  const messages = showingThread ? thread.messages : [];
  const loadingThread =
    !!convId && !showingThread && !(threadError && threadError.id === convId);
  const shownThreadError = threadError && threadError.id === convId ? threadError.message : null;

  useEffect(() => {
    if (!authLoading && !user) router.push("/login");
  }, [authLoading, user, router]);

  const refreshConversations = useCallback(async () => {
    if (!token) return;
    try {
      setConversations(await getCopilotConversations(token));
    } catch {
      setConversations((prev) => prev ?? []);
    }
  }, [token]);

  const refreshMemories = useCallback(async () => {
    if (!token) return;
    try {
      setMemories(await getCopilotMemories(token));
      setMemoryError(null);
    } catch (err) {
      setMemories((prev) => prev ?? []);
      setMemoryError(err instanceof Error ? err.message : "Failed to load memories");
    }
  }, [token]);

  // Initial loads.
  useEffect(() => {
    if (!token || !isSeeker) return;
    let cancelled = false;
    getCopilotStatus(token)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        if (!cancelled) setStatus({ mode: "fallback", provider: null, model: null, tools: [] });
      });
    getCopilotConversations(token)
      .then((c) => {
        if (!cancelled) setConversations(c);
      })
      .catch(() => {
        if (!cancelled) setConversations([]);
      });
    getCopilotMemories(token)
      .then((m) => {
        if (!cancelled) setMemories(m);
      })
      .catch((err) => {
        if (cancelled) return;
        setMemories([]);
        setMemoryError(err instanceof Error ? err.message : "Failed to load memories");
      });
    return () => {
      cancelled = true;
    };
  }, [token, isSeeker]);

  // Load the conversation named in the URL (unless it's already the one in memory).
  useEffect(() => {
    if (!token || !isSeeker || !convId || threadId === convId) return;
    let cancelled = false;
    getCopilotConversation(convId, token)
      .then((c) => {
        if (cancelled) return;
        setThread({ id: c.id, messages: c.messages.map(fromApiMessage) });
        setThreadError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setThreadError({
          id: convId,
          message: err instanceof Error ? err.message : "Failed to load conversation",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [token, isSeeker, convId, threadId]);

  // Auto-scroll to the newest message / typing indicator.
  const messageCount = messages.length;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messageCount, pending, convId]);

  const openConversation = (id: string | null) => {
    setSidebarOpen(false);
    setError(null);
    if (id === convId) return;
    if (id === null) setThread({ id: null, messages: [] });
    setConversationInUrl(id);
    textareaRef.current?.focus();
  };

  const send = async (raw: string) => {
    const message = raw.trim();
    if (!message || pending || !token || loadingThread) return;
    if (message.length > MAX_MESSAGE) {
      setError(`Messages are limited to ${MAX_MESSAGE} characters.`);
      return;
    }
    const fromId = convId;
    localSeq.current += 1;
    const tempId = `local-${localSeq.current}`;
    const optimistic: UiMessage = {
      id: tempId,
      role: "user",
      content: message,
      cards: [],
      trace: [],
      memoriesUsed: [],
      mode: null,
      model: null,
    };
    setThread((prev) => ({
      id: fromId,
      messages: [...(showingThread ? prev.messages : []), optimistic],
    }));
    setInput("");
    setError(null);
    setPending("chat");
    try {
      const res = await copilotChat(
        fromId ? { message, conversation_id: fromId } : { message },
        token,
      );
      // Only touch the visible thread if the user is still looking at it.
      if (currentUrlConversation() === fromId) {
        setThread((prev) =>
          prev.id === fromId
            ? {
                id: res.conversation_id,
                aliasOf: fromId,
                messages: [...prev.messages, fromChatResponse(res)],
              }
            : prev,
        );
        if (fromId !== res.conversation_id) setConversationInUrl(res.conversation_id, "replace");
      }
      if (res.mode && status && res.mode !== status.mode) {
        setStatus({ ...status, mode: res.mode, model: res.model ?? status.model });
      }
      void refreshConversations();
      if (res.trace?.some((t) => t.writes)) void refreshMemories();
    } catch (err) {
      setThread((prev) => ({ ...prev, messages: prev.messages.filter((m) => m.id !== tempId) }));
      // Give the text back so nothing typed is lost.
      setInput((current) => (current.trim() ? current : message));
      setError(err instanceof Error ? err.message : "The copilot couldn't answer. Try again.");
    } finally {
      setPending(null);
      textareaRef.current?.focus();
    }
  };

  const runDigest = async () => {
    if (!token || pending) return;
    setError(null);
    setSidebarOpen(false);
    setPending("digest");
    try {
      const res = await copilotDigest(token);
      // Force a fresh load of the "Daily matches" conversation (it may hold earlier digests).
      setThread({ id: null, messages: [] });
      setThreadError(null);
      setConversationInUrl(
        res.conversation_id,
        res.conversation_id === currentUrlConversation() ? "replace" : "push",
      );
      void refreshConversations();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't fetch today's matches.");
    } finally {
      setPending(null);
    }
  };

  const removeConversation = async (id: string, title: string) => {
    if (!token) return;
    if (!window.confirm(`Delete “${title || "this chat"}”? This can't be undone.`)) return;
    try {
      await deleteCopilotConversation(id, token);
      setConversations((prev) => (prev ? prev.filter((c) => c.id !== id) : prev));
      if (id === convId) {
        setThread({ id: null, messages: [] });
        setConversationInUrl(null, "replace");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete conversation");
    }
  };

  const addMemory = async (content: string, kind: CopilotMemoryKind) => {
    if (!token) return false;
    try {
      const m = await addCopilotMemory({ content, kind }, token);
      setMemories((prev) => [m, ...(prev ?? []).filter((x) => x.id !== m.id)]);
      setMemoryError(null);
      return true;
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : "Failed to save memory");
      return false;
    }
  };

  const removeMemory = async (id: string) => {
    if (!token) return;
    const before = memories;
    setMemories((prev) => (prev ? prev.filter((m) => m.id !== id) : prev));
    try {
      await deleteCopilotMemory(id, token);
    } catch (err) {
      setMemories(before);
      setMemoryError(err instanceof Error ? err.message : "Failed to delete memory");
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(input);
    }
  };

  // Auto-grow the composer up to ~6 lines.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // ---------------- guards ---------------- //

  if (authLoading || !user) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-teal-400" />
      </div>
    );
  }

  if (!isSeeker) {
    return (
      <div className="mx-auto max-w-lg px-4 py-20 text-center">
        <Bot className="mx-auto h-10 w-10 text-zinc-600" />
        <h1 className="mt-4 text-xl font-bold text-zinc-100">Career Copilot is for job seekers</h1>
        <p className="mt-2 text-sm text-zinc-400">
          The copilot works with a seeker&apos;s profile, matches and saved jobs. Sign in with a
          job-seeker account to use it.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 inline-flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2 text-sm text-zinc-300 hover:text-zinc-100"
        >
          Back to dashboard
        </Link>
      </div>
    );
  }

  const activeTitle =
    conversations?.find((c) => c.id === convId)?.title ?? (convId ? "Conversation" : "New chat");

  const sidebar = (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => openConversation(null)}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-teal-500 px-3 py-2 text-sm font-semibold text-zinc-950 shadow-sm shadow-teal-500/20 transition-all hover:bg-teal-400 active:scale-[0.98]"
        >
          <Plus className="h-4 w-4" /> New chat
        </button>
        <button
          type="button"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close sidebar"
          className="rounded-lg border border-zinc-800 p-2 text-zinc-400 hover:text-zinc-200 md:hidden"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <button
        type="button"
        onClick={runDigest}
        disabled={!!pending}
        className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-200 transition-colors hover:bg-amber-500/15 disabled:opacity-50"
      >
        {pending === "digest" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Sun className="h-4 w-4 text-amber-400" />
        )}
        Today&apos;s matches
      </button>

      <div className="grid grid-cols-2 gap-1 rounded-lg border border-zinc-800/80 bg-zinc-900/40 p-1" role="tablist">
        {(
          [
            { key: "chats", label: "Chats", icon: MessageSquare, count: conversations?.length },
            { key: "memory", label: "Memory", icon: Brain, count: memories?.length },
          ] as const
        ).map(({ key, label, icon: Icon, count }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-semibold transition-colors ${
              tab === key ? "bg-zinc-800 text-teal-300" : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
            {typeof count === "number" && count > 0 && (
              <span className="rounded-full bg-zinc-950/60 px-1.5 text-[10px] tabular-nums text-zinc-400">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "chats" ? (
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {conversations === null ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-900/60" />
              ))}
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-1 py-4 text-center text-xs text-zinc-500">
              No chats yet — ask anything to start one.
            </p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((c) => {
                const active = c.id === convId;
                return (
                  <li key={c.id} className="group relative">
                    <button
                      type="button"
                      onClick={() => openConversation(c.id)}
                      className={`flex w-full items-start gap-2 rounded-lg px-2.5 py-2 pr-9 text-left transition-colors ${
                        active
                          ? "bg-zinc-800/80 ring-1 ring-inset ring-teal-500/30"
                          : "hover:bg-zinc-900/70"
                      }`}
                    >
                      {c.title === "Daily matches" ? (
                        <Sun className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                      ) : (
                        <MessageSquare
                          className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${active ? "text-teal-400" : "text-zinc-500"}`}
                        />
                      )}
                      <span className="min-w-0">
                        <span className={`block truncate text-sm ${active ? "font-semibold text-zinc-100" : "text-zinc-300"}`}>
                          {c.title || "Untitled chat"}
                        </span>
                        <span className="block text-[10px] text-zinc-500">
                          {relativeTime(c.updated_at)}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => removeConversation(c.id, c.title)}
                      title="Delete chat"
                      aria-label={`Delete chat ${c.title}`}
                      className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5 text-zinc-500 opacity-100 transition-opacity hover:bg-rose-500/10 hover:text-rose-400 focus:opacity-100 md:opacity-0 md:group-hover:opacity-100"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : (
        <MemoryPanel
          memories={memories}
          error={memoryError}
          onAdd={addMemory}
          onDelete={removeMemory}
        />
      )}
    </div>
  );

  const busy = !!pending || loadingThread;
  const isEmpty = !convId && messages.length === 0;

  return (
    <div className="mx-auto flex h-[calc(100dvh-4rem)] max-w-7xl">
      {/* Desktop sidebar */}
      <aside className="hidden w-72 shrink-0 border-r border-zinc-800/80 md:flex md:flex-col">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {sidebarOpen && (
        <div className="fixed inset-x-0 bottom-0 top-16 z-30 md:hidden">
          <button
            type="button"
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
            className="absolute inset-0 bg-zinc-950/70 backdrop-blur-sm"
          />
          <aside className="relative flex h-full w-[85%] max-w-xs flex-col border-r border-zinc-800 bg-zinc-950 shadow-2xl">
            {sidebar}
          </aside>
        </div>
      )}

      {/* Chat pane */}
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-zinc-800/80 px-4 py-3">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open chats and memory"
            className="rounded-lg border border-zinc-800 p-2 text-zinc-400 hover:text-zinc-200 md:hidden"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950 shadow-md shadow-teal-500/10">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-bold text-zinc-100">Career Copilot</h1>
            <p className="truncate text-[11px] text-zinc-500">
              {pending ? "typing…" : activeTitle}
            </p>
          </div>
          <StatusBadge status={status} />
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {loadingThread ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin text-teal-400" /> Loading conversation…
            </div>
          ) : shownThreadError ? (
            <div className="mx-auto mt-10 max-w-md rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
              <p className="flex items-center gap-2 font-semibold">
                <AlertCircle className="h-4 w-4" /> Couldn&apos;t open this chat
              </p>
              <p className="mt-1 text-xs text-rose-300/80">{shownThreadError}</p>
              <button
                type="button"
                onClick={() => openConversation(null)}
                className="mt-3 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-zinc-200 hover:bg-zinc-800"
              >
                Start a new chat
              </button>
            </div>
          ) : isEmpty && !pending ? (
            <div className="mx-auto flex max-w-2xl flex-col items-center py-8 text-center sm:py-14">
              <div className="relative">
                <div className="absolute inset-0 rounded-full bg-teal-500/20 blur-2xl" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-400 to-cyan-600 text-zinc-950 shadow-lg shadow-teal-500/20">
                  <Bot className="h-8 w-8" />
                </div>
              </div>
              <h2 className="mt-5 text-2xl font-bold tracking-tight text-zinc-100">
                Your Career Copilot
              </h2>
              <p className="mt-2 max-w-md text-sm text-zinc-400">
                Ask in plain language. It searches jobs, ranks your matches, explains skill gaps,
                saves jobs and tailors your resume — and remembers what matters to you.
              </p>
              <div className="mt-7 flex flex-wrap justify-center gap-2">
                {SUGGESTED_PROMPTS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => void send(p)}
                    disabled={busy}
                    className="rounded-full border border-zinc-800 bg-zinc-900/60 px-3.5 py-2 text-left text-xs font-medium text-zinc-300 transition-colors hover:border-teal-500/50 hover:bg-teal-500/5 hover:text-teal-200 disabled:opacity-50"
                  >
                    {p}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={runDigest}
                disabled={busy}
                className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-300 hover:text-amber-200 disabled:opacity-50"
              >
                <Sun className="h-3.5 w-3.5 text-amber-400" /> Or get today&apos;s top matches
              </button>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
              {pending && (
                <TypingIndicator
                  label={
                    pending === "digest"
                      ? "Picking today's best matches…"
                      : "Working — searching, ranking and checking your skills…"
                  }
                />
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div className="border-t border-zinc-800/80 bg-zinc-950/80 px-3 py-3 backdrop-blur sm:px-6">
          <div className="mx-auto max-w-3xl">
            {error && (
              <div className="mb-2 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" />
                <span className="flex-1">{error}</span>
                <button
                  type="button"
                  onClick={() => setError(null)}
                  aria-label="Dismiss error"
                  className="text-rose-300/70 hover:text-rose-200"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void send(input);
              }}
              className="flex items-end gap-2 rounded-2xl border border-zinc-800 bg-zinc-900/70 p-1.5 pl-3 focus-within:border-teal-500/50"
            >
              <UserIcon className="mb-2.5 h-4 w-4 shrink-0 text-zinc-600" aria-hidden />
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                maxLength={MAX_MESSAGE}
                placeholder="Ask your copilot…"
                aria-label="Message the copilot"
                className="max-h-40 min-h-[2.25rem] flex-1 resize-none bg-transparent py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none"
              />
              <button
                type="submit"
                disabled={busy || !input.trim()}
                aria-label="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-500 text-zinc-950 shadow-sm shadow-teal-500/20 transition-all hover:bg-teal-400 active:scale-95 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:shadow-none"
              >
                {pending === "chat" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <SendHorizontal className="h-4 w-4" />
                )}
              </button>
            </form>
            <p className="mt-1.5 hidden text-center text-[10px] text-zinc-600 sm:block">
              Enter to send · Shift+Enter for a new line
              {input.length > MAX_MESSAGE - 200 && ` · ${input.length}/${MAX_MESSAGE}`}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function CopilotPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[70vh] items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-teal-400" />
        </div>
      }
    >
      <CopilotView />
    </Suspense>
  );
}
