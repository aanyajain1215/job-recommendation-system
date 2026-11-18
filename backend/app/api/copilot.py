"""Career Copilot API — conversational, tool-using job-search agent.

POST /copilot/chat                 one turn (agent loop or deterministic router)
POST /copilot/digest               "morning drop": ranked matches posted as a chat message
GET  /copilot/status               which mode/model is serving
GET  /copilot/conversations        list
GET  /copilot/conversations/{id}   messages (with cards + tool trace)
DELETE /copilot/conversations/{id}
GET/POST/DELETE /copilot/memories  long-term memory the user can inspect and edit
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.core.db import get_db
from app.models.copilot import CopilotConversation, CopilotMessage
from app.models.enums import UserRole
from app.models.user import User
from app.services.agent import memory as mem
from app.services.agent.copilot import (
    _persist_reply,
    after_turn,
    get_or_create_conversation,
    run_turn,
)
from app.services.agent.fallback import _job_lines
from app.services.agent.tools import AgentContext, execute

router = APIRouter(prefix="/copilot", tags=["copilot"])

Seeker = Annotated[User, Depends(require_roles(UserRole.JOB_SEEKER))]
DIGEST_TITLE = "Daily matches"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    reply: str
    cards: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    mode: Literal["llm", "fallback"]
    memories_used: list[str] = Field(default_factory=list)
    model: str | None = None


class ConversationOut(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    created_at: datetime


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    meta: dict[str, Any] | None = None


class ConversationDetail(ConversationOut):
    summary: str | None = None
    messages: list[MessageOut]


class MemoryIn(BaseModel):
    content: str = Field(min_length=4, max_length=240)
    kind: Literal["preference", "dealbreaker", "goal", "fact"] = "preference"


class MemoryOut(BaseModel):
    id: UUID
    kind: str
    content: str
    source: str
    updated_at: datetime


class StatusOut(BaseModel):
    mode: Literal["llm", "fallback"]
    provider: str | None = None
    model: str | None = None
    tools: list[str]


def _owned(db: Session, user: User, conversation_id: UUID) -> CopilotConversation:
    conv = db.get(CopilotConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conv


@router.get("/status", response_model=StatusOut)
def copilot_status(current_user: Seeker) -> StatusOut:
    from app.services.agent.tools import TOOLS
    from app.services.llm.provider import get_tool_provider

    provider = None
    if get_settings().agent_enabled:
        try:
            provider = get_tool_provider()
        except Exception:  # noqa: BLE001 - strict mode raises; status must not
            provider = None
    return StatusOut(
        mode="llm" if provider is not None else "fallback",
        provider=getattr(provider, "name", None),
        model=getattr(provider, "model", None),
        tools=sorted(TOOLS),
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limited("copilot"))])
def chat(
    payload: ChatRequest,
    background: BackgroundTasks,
    current_user: Seeker,
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    if payload.conversation_id is not None:
        _owned(db, current_user, payload.conversation_id)
    result = run_turn(db, current_user, payload.message.strip(), payload.conversation_id)
    if result.mode == "llm":
        background.add_task(after_turn, current_user.id, result.conversation_id, payload.message)
    return ChatResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        reply=result.reply,
        cards=result.cards,
        trace=result.trace,
        mode=result.mode,  # type: ignore[arg-type]
        memories_used=result.memories_used,
        model=result.model,
    )


@router.post("/digest", response_model=ChatResponse)
def morning_digest(current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> ChatResponse:
    """Post today's top matches into the user's "Daily matches" thread.

    Jobs already saved/applied are skipped and every line is templated from
    engine output (scores, reasons, gaps) — grounded by construction.
    """
    conv = db.scalar(
        select(CopilotConversation)
        .where(CopilotConversation.user_id == current_user.id, CopilotConversation.title == DIGEST_TITLE)
        .order_by(CopilotConversation.updated_at.desc())
        .limit(1)
    )
    if conv is None:
        conv = get_or_create_conversation(db, current_user, None)
        conv.title = DIGEST_TITLE
        db.commit()

    ctx = AgentContext(db=db, user=current_user)
    trace: list[dict[str, Any]] = []
    tracked = execute(ctx, "list_my_applications", {})
    tracked_ids = {a["job_id"] for a in tracked.data.get("applications", [])} if tracked.ok else set()
    recs = execute(ctx, "get_recommendations", {"limit": 8})
    trace.append({"tool": "get_recommendations", "args": {"limit": 8}, "ok": recs.ok, "ms": 0, "writes": False})

    if not recs.ok:
        reply = f"I couldn't build today's matches: {recs.data.get('error')}"
        cards: list[dict[str, Any]] = []
    else:
        job_cards = [c for c in recs.cards if c.get("type") == "job" and c["id"] not in tracked_ids][:5]
        other = [c for c in recs.cards if c.get("type") != "job"]
        ctx.last_list = [c["id"] for c in job_cards]
        for c in job_cards:
            ctx.seen_jobs[c["id"]] = c
        if not job_cards:
            reply = "Good morning! Nothing new beyond what you've already saved — I'll keep looking."
        else:
            jobs_view = [
                {
                    "ref": i,
                    "title": c["title"],
                    "company": c["company"],
                    "match_score": c["match_score"],
                    "missing_skills": c["missing_skills"],
                }
                for i, c in enumerate(job_cards, start=1)
            ]
            reply = f"Good morning! Your {len(job_cards)} best matches today:\n" + _job_lines(jobs_view)
            gap = next((c for c in other if c.get("type") == "skill_gap_summary"), None)
            if gap and gap.get("headline"):
                reply += f"\n\nPattern: {gap['headline']}"
            reply += "\n\nReply “why 1” for the full breakdown or “save 2” to track one."
        cards = job_cards + other

    result = _persist_reply(db, conv, ctx, reply=reply, cards=cards, trace=trace, mode="fallback")
    return ChatResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        reply=result.reply,
        cards=result.cards,
        trace=result.trace,
        mode="fallback",
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> list[ConversationOut]:
    rows = db.scalars(
        select(CopilotConversation)
        .where(CopilotConversation.user_id == current_user.id)
        .order_by(CopilotConversation.updated_at.desc())
        .limit(50)
    ).all()
    return [ConversationOut(id=r.id, title=r.title, updated_at=r.updated_at, created_at=r.created_at) for r in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID, current_user: Seeker, db: Annotated[Session, Depends(get_db)]
) -> ConversationDetail:
    conv = _owned(db, current_user, conversation_id)
    msgs = db.scalars(
        select(CopilotMessage)
        .where(CopilotMessage.conversation_id == conv.id, CopilotMessage.role.in_(("user", "assistant")))
        .order_by(CopilotMessage.created_at)
    ).all()
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        updated_at=conv.updated_at,
        created_at=conv.created_at,
        summary=conv.summary,
        messages=[
            MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at, meta=m.meta) for m in msgs
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: UUID, current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> None:
    conv = _owned(db, current_user, conversation_id)
    db.delete(conv)
    db.commit()


@router.get("/memories", response_model=list[MemoryOut])
def get_memories(current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> list[MemoryOut]:
    return [
        MemoryOut(id=m.id, kind=m.kind, content=m.content, source=m.source, updated_at=m.updated_at)
        for m in mem.list_memories(db, current_user.id)
    ]


@router.post("/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
def add_memory(payload: MemoryIn, current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> MemoryOut:
    row, _created = mem.upsert_memory(db, current_user.id, payload.content, kind=payload.kind, source="user")
    if row is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Memory too short.")
    return MemoryOut(id=row.id, kind=row.kind, content=row.content, source=row.source, updated_at=row.updated_at)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_memory(memory_id: UUID, current_user: Seeker, db: Annotated[Session, Depends(get_db)]) -> None:
    if not mem.delete_memory(db, current_user.id, memory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
