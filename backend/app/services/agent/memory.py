"""Career Copilot memory: long-term facts + rolling conversation summary.

Long-term memory (``copilot_memories``)
    * **Write** — the agent's ``remember`` tool, plus an after-turn extractor
      that pulls durable facts the *user* stated (structured output, schema
      validated, kinds whitelisted).
    * **Dedupe** — a new fact whose embedding is ≥ ``DUP_COSINE`` similar to an
      existing one *replaces* it (preferences change: "now open to Bangalore").
    * **Recall** — dealbreakers are always injected; the rest are ranked by
      cosine similarity to the current message (pgvector) and capped at
      ``agent_memory_top_k``.

Short-term memory
    * The last ``agent_history_messages`` messages are replayed verbatim;
      older ones are folded into ``copilot_conversations.summary`` by an LLM
      summariser (deterministic truncation fallback without a provider).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.copilot import MEMORY_KINDS, CopilotConversation, CopilotMemory, CopilotMessage

log = logging.getLogger(__name__)

DUP_COSINE = 0.88
MAX_MEMORIES_PER_USER = 60
MAX_MEMORY_CHARS = 240


# ---------------------------------------------------------------------------
# CRUD + recall
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float] | None:
    try:
        from app.services.embeddings import get_embedder

        return get_embedder().encode_one(text)
    except Exception:  # pragma: no cover - embeddings are best effort
        log.debug("memory embedding failed", exc_info=True)
        return None


def _cos(a: list[float] | None, b: list[float] | None) -> float:
    if a is None or b is None:
        return 0.0
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


def list_memories(db: Session, user_id: UUID) -> list[CopilotMemory]:
    return list(
        db.scalars(
            select(CopilotMemory)
            .where(CopilotMemory.user_id == user_id)
            .order_by(CopilotMemory.updated_at.desc())
        ).all()
    )


def upsert_memory(
    db: Session,
    user_id: UUID,
    content: str,
    *,
    kind: str = "fact",
    source: str = "chat",
) -> tuple[CopilotMemory | None, bool]:
    """Insert a memory, or replace a near-duplicate. Returns (row, created)."""
    text = " ".join(str(content or "").split())[:MAX_MEMORY_CHARS]
    if len(text) < 4:
        return None, False
    kind = kind if kind in MEMORY_KINDS else "fact"
    vec = _embed(text)

    existing = list_memories(db, user_id)
    for mem in existing:
        same_text = mem.content.strip().lower() == text.lower()
        if same_text or (vec is not None and _cos(vec, mem.embedding) >= DUP_COSINE):
            mem.content = text
            mem.kind = kind
            mem.embedding = vec
            mem.updated_at = datetime.now(timezone.utc)
            db.commit()
            return mem, False

    if len(existing) >= MAX_MEMORIES_PER_USER:
        # drop the stalest non-dealbreaker to stay bounded
        victims = [m for m in existing if m.kind != "dealbreaker"] or existing
        db.delete(victims[-1])

    mem = CopilotMemory(user_id=user_id, kind=kind, content=text, source=source, embedding=vec)
    db.add(mem)
    db.commit()
    db.refresh(mem)
    return mem, True


def delete_memory(db: Session, user_id: UUID, memory_id: str | UUID) -> bool:
    try:
        mid = UUID(str(memory_id))
    except ValueError:
        return False
    mem = db.get(CopilotMemory, mid)
    if mem is None or mem.user_id != user_id:
        return False
    db.delete(mem)
    db.commit()
    return True


def recall(db: Session, user_id: UUID, query: str, k: int | None = None) -> list[CopilotMemory]:
    """Dealbreakers always + top-k most relevant others (cosine to query)."""
    k = k or get_settings().agent_memory_top_k
    memories = list_memories(db, user_id)
    if len(memories) <= k:
        return memories
    pinned = [m for m in memories if m.kind == "dealbreaker"]
    rest = [m for m in memories if m.kind != "dealbreaker"]
    qvec = _embed(query) if query.strip() else None
    if qvec is not None:
        rest.sort(key=lambda m: -_cos(qvec, m.embedding))
    return (pinned + rest)[: max(k, len(pinned))]


# ---------------------------------------------------------------------------
# LLM extraction (after each turn)
# ---------------------------------------------------------------------------

class _NewMemory(BaseModel):
    kind: Literal["preference", "dealbreaker", "goal", "fact"]
    content: str = Field(max_length=MAX_MEMORY_CHARS)


class MemoryOps(BaseModel):
    add: list[_NewMemory] = Field(default_factory=list, max_length=5)
    forget_ids: list[str] = Field(default_factory=list, max_length=5)


def _extraction_prompt(user_message: str, memories: list[CopilotMemory]) -> str:
    known = "\n".join(f"- [{m.id}] ({m.kind}) {m.content}" for m in memories) or "(none)"
    return f"""You maintain long-term memory for a job-search assistant.

From the USER MESSAGE below, extract durable facts about the user that will matter in future job searches:
preferences (locations, work mode, company size, industries, salary), dealbreakers (things they refuse),
career goals (target roles, switches), and stable facts (graduation year, notice period, visa status).

Rules:
- Only facts the USER explicitly stated about themselves. Never infer, never store facts about jobs.
- Short third-person statements, e.g. "Prefers remote roles", "Will not work night shifts".
- Skip anything already covered by KNOWN MEMORIES unless it changed; if a known memory is now
  contradicted, put its id in forget_ids and add the new version.
- Never store passwords, phone numbers, emails, addresses or ID numbers.
- Most messages contain nothing worth storing: return empty lists then.

Return JSON: {{"add": [{{"kind": "...", "content": "..."}}], "forget_ids": ["..."]}}

KNOWN MEMORIES:
{known}

USER MESSAGE:
{user_message[:2000]}"""


_PII_MARKERS = ("@", "password", "passcode", "aadhaar", "pan card", "ssn")


def extract_and_store(db: Session, user_id: UUID, user_message: str) -> list[str]:
    """Run the extractor and apply its ops. Returns stored memory texts."""
    from app.services.llm.provider import get_provider

    if len(user_message.strip()) < 12:
        return []
    provider = get_provider()
    if provider is None:
        return []
    memories = list_memories(db, user_id)
    try:
        ops, _usage = provider.complete_json(
            MemoryOps,
            _extraction_prompt(user_message, memories),
            max_tokens=400,
            route="agent_memory",
        )
    except Exception:  # noqa: BLE001 - memory is best effort
        log.info("memory extraction failed", exc_info=True)
        return []

    known_ids = {str(m.id) for m in memories}
    for mid in ops.forget_ids:
        if mid in known_ids:
            delete_memory(db, user_id, mid)
    stored: list[str] = []
    for item in ops.add:
        text = item.content.strip()
        if any(marker in text.lower() for marker in _PII_MARKERS) or sum(c.isdigit() for c in text) > 6:
            continue  # validator: no contact details / long digit strings
        mem, _created = upsert_memory(db, user_id, text, kind=item.kind, source="chat")
        if mem is not None:
            stored.append(mem.content)
    return stored


# ---------------------------------------------------------------------------
# Rolling summary
# ---------------------------------------------------------------------------

class _Summary(BaseModel):
    summary: str = Field(max_length=1500)


def maybe_summarize(db: Session, conversation: CopilotConversation) -> bool:
    """Fold messages older than the replay window into ``summary``."""
    settings = get_settings()
    total = db.scalar(
        select(func.count()).select_from(CopilotMessage).where(
            CopilotMessage.conversation_id == conversation.id
        )
    ) or 0
    if total <= settings.agent_summarize_after:
        return False

    keep = settings.agent_history_messages
    rows = list(
        db.scalars(
            select(CopilotMessage)
            .where(CopilotMessage.conversation_id == conversation.id)
            .order_by(CopilotMessage.created_at)
        ).all()
    )
    old = rows[:-keep]
    if conversation.summarized_until is not None:
        old = [m for m in old if m.created_at > conversation.summarized_until]
    old = [m for m in old if m.role in ("user", "assistant") and m.content.strip()]
    if not old:
        return False

    transcript = "\n".join(f"{m.role.upper()}: {m.content[:600]}" for m in old)
    previous = conversation.summary or ""
    new_summary: str | None = None
    try:
        from app.services.llm.provider import get_provider

        provider = get_provider()
        if provider is not None:
            out, _usage = provider.complete_json(
                _Summary,
                (
                    "Update the running summary of a job-search chat. Keep: what the user is looking for, "
                    "jobs discussed (title @ company), decisions made, open questions. Max 120 words.\n\n"
                    f"PREVIOUS SUMMARY:\n{previous or '(none)'}\n\nNEW MESSAGES:\n{transcript[:6000]}\n\n"
                    'Return JSON: {"summary": "..."}'
                ),
                max_tokens=300,
                route="agent_summary",
            )
            new_summary = out.summary
    except Exception:  # noqa: BLE001
        log.info("conversation summary failed; using truncation", exc_info=True)

    if not new_summary:
        # deterministic fallback: keep the user's recent asks
        asks = [m.content[:120] for m in old if m.role == "user"][-6:]
        new_summary = (previous + " | Earlier the user asked: " + "; ".join(asks)).strip(" |")[-1500:]

    conversation.summary = new_summary
    conversation.summarized_until = old[-1].created_at
    db.commit()
    return True
