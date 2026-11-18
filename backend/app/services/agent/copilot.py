"""Career Copilot — a tool-using, memory-backed job-search agent.

One user turn:

1. Load/create the conversation, persist the user message.
2. Build context: system rules + profile snapshot + recalled long-term
   memories + rolling summary + the last N messages (assistant messages carry
   a compact list of the jobs they showed, so "save the 2nd one" resolves
   across turns).
3. ReAct-style loop (≤ ``agent_max_steps``): the model either answers or
   requests native tool calls; tools run against the real services and their
   compact JSON goes back to the model.  Unknown tools / bad arguments come
   back as readable errors so the model can self-correct.
4. Persist the assistant reply with UI cards + a tool trace (transparency:
   the chat shows which tools ran, with timings).
5. After the response: extract long-term memories, fold old turns into the
   summary (background task, own DB session).

No provider (or ``AGENT_ENABLED=false``) → a deterministic intent router
(``fallback.py``) drives the same tools, so the feature never 500s.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.copilot import CopilotConversation, CopilotMessage
from app.models.user import User
from app.services.agent import memory as mem
from app.services.agent.tools import TOOLS, AgentContext, execute, get_profile, tool_schemas
from app.services.llm.provider import assistant_tool_message
from app.services.llm.strict import LlmStrictError, strict_bail

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 6000


@dataclass
class TurnResult:
    conversation_id: UUID
    message_id: UUID
    reply: str
    cards: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "llm"                  # "llm" | "fallback"
    memories_used: list[str] = field(default_factory=list)
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


SYSTEM_RULES = """You are JobRec Copilot, a job-search agent the user chats with like a friend on WhatsApp.
You find, rank and explain jobs, show skill gaps, help career switchers and tailor resumes, using TOOLS.

Hard rules:
1. Any fact about jobs, match scores, skills or applications MUST come from a tool result in this conversation.
   Never invent job titles, companies, salaries, scores or links. If you have not called a tool, call one.
2. Scores come from a deterministic ranking engine — quote them exactly as returned, never estimate your own.
   Label them precisely: `match_score` is the overall match ("82% match"); `skill_match_pct` is only the share
   of the job's listed skills the user has ("60% skill match"). Search results usually carry only skill_match_pct.
3. Write tools (save_job, update_career_direction, forget) ONLY when the user explicitly asks for that change.
   Call `remember` when the user states a durable preference, dealbreaker or goal.
4. Respect the user's dealbreakers from memory: skip or clearly flag jobs that violate them.
5. Be brief (under ~120 words). The UI renders job cards from tool results, so list jobs compactly:
   "1. Title — Company · 82% match · missing: Docker". For each job: one reason it fits, one gap.
6. When listing jobs, keep the order the tool returned and number each with its `ref` — never re-sort or
   renumber — so "the second one" means the same job to you and the user. Pass that ref (or the id) to tools.
7. If a tool fails, say so in one line and suggest the next step. Never pretend an action succeeded.
8. Stay on careers and job search; politely steer back otherwise.
9. Indian hiring terms: "fresher", "graduate", "trainee", "0-1 years", "2026 batch" mean entry level - pass
   experience_level="entry". Each job carries its `level`; never present a senior/lead role to a fresher.
   `level: "not stated"` means the posting gives no seniority (it is NOT mid-level) — list confirmed entry roles first."""


# ---------------------------------------------------------------------------
# conversation helpers
# ---------------------------------------------------------------------------

def get_or_create_conversation(db: Session, user: User, conversation_id: UUID | None) -> CopilotConversation:
    if conversation_id is not None:
        conv = db.get(CopilotConversation, conversation_id)
        if conv is not None and conv.user_id == user.id:
            return conv
    conv = CopilotConversation(user_id=user.id, title="New conversation")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _history(db: Session, conv: CopilotConversation, limit: int) -> list[CopilotMessage]:
    rows = list(
        db.scalars(
            select(CopilotMessage)
            .where(
                CopilotMessage.conversation_id == conv.id,
                CopilotMessage.role.in_(("user", "assistant")),
            )
            .order_by(CopilotMessage.created_at.desc())
            .limit(limit)
        ).all()
    )
    return list(reversed(rows))


def _shown_note(meta: dict[str, Any] | None) -> str:
    shown = (meta or {}).get("shown") or []
    if not shown:
        return ""
    lines = [f"{s['ref']}) id={s['id']} {s['title']} @ {s.get('company') or '?'}" for s in shown[:8]]
    return "\n[Jobs shown in this reply: " + "; ".join(lines) + "]"


def _restore_context(ctx: AgentContext, history: list[CopilotMessage]) -> None:
    """Rebuild seen jobs + last list from earlier assistant messages."""
    for msg in history:
        if msg.role != "assistant" or not msg.meta:
            continue
        for card in msg.meta.get("cards") or []:
            if card.get("type") == "job" and card.get("id"):
                ctx.seen_jobs[card["id"]] = card
        shown = msg.meta.get("shown") or []
        if shown:
            ctx.last_list = [s["id"] for s in shown]


def _profile_snapshot(ctx: AgentContext) -> str:
    res = get_profile(ctx)
    if not res.ok:
        return "Profile: not created yet."
    d = res.data
    parts = []
    for key, label in (
        ("headline", "Headline"),
        ("years_of_experience", "Years of experience"),
        ("location", "Location"),
        ("target_roles", "Target roles"),
        ("target_family", "Target family"),
        ("preferred_work_mode", "Work mode"),
        ("expected_salary", "Expected salary"),
    ):
        if key in d:
            val = d[key]
            parts.append(f"{label}: {', '.join(val) if isinstance(val, list) else val}")
    if d.get("skills"):
        parts.append("Top skills: " + ", ".join(d["skills"][:15]))
    return "User profile snapshot:\n" + "\n".join(f"- {p}" for p in parts)


def build_messages(
    ctx: AgentContext,
    conv: CopilotConversation,
    history: list[CopilotMessage],
    memories: list[Any],
) -> list[dict[str, Any]]:
    system = [SYSTEM_RULES, f"Today is {date.today().isoformat()}.", _profile_snapshot(ctx)]
    if memories:
        system.append(
            "Long-term memory about the user (id → fact):\n"
            + "\n".join(f"- [{m.id}] ({m.kind}) {m.content}" for m in memories)
        )
    if conv.summary:
        system.append(f"Summary of earlier conversation:\n{conv.summary}")
    messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(system)}]
    for m in history:
        content = m.content
        if m.role == "assistant":
            content += _shown_note(m.meta)
        messages.append({"role": m.role, "content": content})
    return messages


def _truncate_json(data: dict[str, Any]) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + '..."(truncated)"'


def _dedupe_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for card in cards:
        key = f"{card.get('type')}:{card.get('id') or card.get('job_id') or card.get('target') or len(out)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def _shown(ctx: AgentContext) -> list[dict[str, Any]]:
    return [
        {
            "ref": i,
            "id": jid,
            "title": ctx.seen_jobs.get(jid, {}).get("title"),
            "company": ctx.seen_jobs.get(jid, {}).get("company"),
        }
        for i, jid in enumerate(ctx.last_list, start=1)
    ]


def _title_from(message: str) -> str:
    text = " ".join(message.split())
    return (text[:60] + "…") if len(text) > 60 else (text or "New conversation")


# ---------------------------------------------------------------------------
# the turn
# ---------------------------------------------------------------------------

def run_turn(db: Session, user: User, message: str, conversation_id: UUID | None = None) -> TurnResult:
    settings = get_settings()
    conv = get_or_create_conversation(db, user, conversation_id)
    history = _history(db, conv, settings.agent_history_messages)

    user_msg = CopilotMessage(conversation_id=conv.id, role="user", content=message)
    db.add(user_msg)
    if conv.title == "New conversation":
        conv.title = _title_from(message)
    db.commit()

    ctx = AgentContext(db=db, user=user, user_message=message)
    _restore_context(ctx, history)

    from app.services.llm.provider import get_tool_provider

    provider = None
    if settings.agent_enabled:
        try:
            provider = get_tool_provider()
        except LlmStrictError:
            raise
        except Exception:  # pragma: no cover - provider construction
            provider = None
    if provider is None:
        strict_bail("copilot", "no tool-calling LLM provider available")
        return _finish_fallback(db, conv, ctx, message)

    memories = mem.recall(db, user.id, message)
    messages = build_messages(ctx, conv, history, memories)
    messages.append({"role": "user", "content": message})

    cards: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    tools = tool_schemas()
    reply = ""
    try:
        for step in range(settings.agent_max_steps + 1):
            final_round = step == settings.agent_max_steps
            turn = provider.chat_tools(
                messages,
                [] if final_round else tools,
                route="copilot",
                temperature=settings.agent_temperature,
            )
            usage["prompt_tokens"] += turn.usage.prompt_tokens
            usage["completion_tokens"] += turn.usage.completion_tokens
            if not turn.tool_calls or final_round:
                reply = turn.content.strip()
                break

            messages.append(assistant_tool_message(turn))
            for call in turn.tool_calls:
                started = time.perf_counter()
                if call.parse_error:
                    from app.services.agent.tools import ToolResult

                    result = ToolResult(data={"error": call.parse_error}, ok=False)
                else:
                    result = execute(ctx, call.name, call.arguments)
                ms = int((time.perf_counter() - started) * 1000)
                trace.append(
                    {
                        "tool": call.name,
                        "args": call.arguments,
                        "ok": result.ok,
                        "ms": ms,
                        "writes": bool(TOOLS.get(call.name) and TOOLS[call.name].writes),
                        "error": result.data.get("error") if not result.ok else None,
                    }
                )
                cards.extend(result.cards)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": _truncate_json(result.data)}
                )
    except LlmStrictError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider/network failure mid-turn
        log.exception("copilot LLM turn failed; using deterministic router")
        strict_bail("copilot", f"LLM turn failed: {exc}")
        return _finish_fallback(db, conv, ctx, message, notice="(AI is unavailable right now — here's what I found directly.)")

    if not reply:
        reply = "Here's what I found." if cards else "Sorry — I couldn't produce an answer. Could you rephrase?"

    return _persist_reply(
        db,
        conv,
        ctx,
        reply=reply,
        cards=cards,
        trace=trace,
        mode="llm",
        memories_used=[m.content for m in memories],
        model=getattr(provider, "model", None),
        usage=usage,
    )


def _persist_reply(
    db: Session,
    conv: CopilotConversation,
    ctx: AgentContext,
    *,
    reply: str,
    cards: list[dict[str, Any]],
    trace: list[dict[str, Any]],
    mode: str,
    memories_used: list[str] | None = None,
    model: str | None = None,
    usage: dict[str, int] | None = None,
) -> TurnResult:
    cards = _dedupe_cards(cards)
    meta = {
        "cards": cards,
        "trace": trace,
        "mode": mode,
        "shown": _shown(ctx) if any(c.get("type") == "job" for c in cards) else [],
        "model": model,
        "usage": usage or {},
        "memories_used": memories_used or [],
    }
    msg = CopilotMessage(conversation_id=conv.id, role="assistant", content=reply, meta=meta)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return TurnResult(
        conversation_id=conv.id,
        message_id=msg.id,
        reply=reply,
        cards=cards,
        trace=trace,
        mode=mode,
        memories_used=memories_used or [],
        model=model,
        usage=usage or {},
    )


def _finish_fallback(
    db: Session,
    conv: CopilotConversation,
    ctx: AgentContext,
    message: str,
    notice: str | None = None,
) -> TurnResult:
    from app.services.agent.fallback import route

    reply, cards, trace = route(ctx, message)
    if notice:
        reply = f"{notice}\n\n{reply}"
    return _persist_reply(db, conv, ctx, reply=reply, cards=cards, trace=trace, mode="fallback")


def after_turn(user_id: UUID, conversation_id: UUID, user_message: str) -> None:
    """Background: long-term memory extraction + rolling summary."""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        try:
            mem.extract_and_store(db, user_id, user_message)
        except Exception:  # noqa: BLE001
            log.exception("copilot memory extraction failed")
            db.rollback()
        try:
            conv = db.get(CopilotConversation, conversation_id)
            if conv is not None:
                mem.maybe_summarize(db, conv)
        except Exception:  # noqa: BLE001
            log.exception("copilot summarization failed")
            db.rollback()
