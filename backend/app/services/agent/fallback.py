"""Deterministic Copilot router — used when no tool-calling LLM is available.

Keyword intent detection drives the *same* tools as the agent, and replies
are templated from tool data only, so the chat keeps working (and stays
grounded) with no API key, under a provider outage, or in tests.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.services.agent.tools import AgentContext, ToolResult, execute

_SAVE = re.compile(r"\bsave\b.*?(?:#|no\.?|number\s*)?(\d+)", re.I)
_EXPLAIN = re.compile(r"\b(?:why|explain|details?|fit|gap)\b.*?(?:#|no\.?|number\s*)?\b(\d+)\b", re.I)
_REMEMBER = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?\s*[:,-]?\s+(.+)$", re.I)
_TAILOR = re.compile(r"\b(?:tailor|optimi[sz]e|improve|ats)\b.*\bresume\b.*?(\d+)?\s*$|\bresume\b.*\b(?:for|to)\b.*?(\d+)", re.I)
_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
             "fifth": 5, "5th": 5, "sixth": 6, "seventh": 7, "eighth": 8, "top": 1}
_ORDINAL = re.compile(
    r"\b(?:the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|sixth|seventh|eighth|top|last)"
    r"(?:\s+(?:one|job|role|posting|listing|option))?\b",
    re.I,
)
_LOCATION = re.compile(r"\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b")
_FILLER = re.compile(
    r"\b(find|show|search|get|me|some|any|for|jobs?|roles?|openings?|positions?|please|looking|i'?m|i am|want|a|an|the|in|near|remote)\b",
    re.I,
)


def _run(ctx: AgentContext, trace: list[dict[str, Any]], name: str, args: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    result = execute(ctx, name, args)
    trace.append(
        {
            "tool": name,
            "args": args,
            "ok": result.ok,
            "ms": int((time.perf_counter() - started) * 1000),
            "writes": name in ("save_job", "remember", "update_career_direction", "forget"),
            "error": result.data.get("error") if not result.ok else None,
        }
    )
    return result


def _job_lines(jobs: list[dict[str, Any]]) -> str:
    lines = []
    for j in jobs:
        bits = [f"{j['ref']}. {j['title']}"]
        if j.get("company"):
            bits[0] += f" — {j['company']}"
        if j.get("match_score") is not None:
            bits.append(f"{j['match_score']}% match")
        elif j.get("skill_match_pct") is not None:
            bits.append(f"{j['skill_match_pct']}% skill match")
        if j.get("missing_skills"):
            bits.append("missing: " + ", ".join(j["missing_skills"][:2]))
        lines.append(" · ".join(bits))
    return "\n".join(lines)


def route(ctx: AgentContext, message: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    text = (message or "").strip()
    low = text.lower()
    trace: list[dict[str, Any]] = []

    if m := _REMEMBER.match(text):
        r = _run(ctx, trace, "remember", {"content": m.group(1), "kind": "preference"})
        reply = f"Got it — I'll remember: “{r.data['remembered']}”." if r.ok else "I couldn't store that."
        return reply, r.cards, trace

    # "the second one" / "first job" / "last one" → positional digits, so the
    # save / explain / tailor intents below resolve against the last list shown
    if ctx.last_list:
        text = _ORDINAL.sub(
            lambda m: str(len(ctx.last_list) if m.group(1).lower() == "last" else _ORDINALS[m.group(1).lower()]),
            text,
        )

    if (m := _SAVE.search(text)) and ctx.last_list:
        r = _run(ctx, trace, "save_job", {"job_ref": m.group(1)})
        reply = f"Saved “{r.data.get('title')}” to your tracker." if r.ok else f"Couldn't save it: {r.data.get('error')}"
        return reply, r.cards, trace

    if (m := _TAILOR.search(text)) and ctx.last_list:
        ref = m.group(1) or m.group(2) or "1"
        r = _run(ctx, trace, "tailor_resume", {"job_ref": ref})
        if not r.ok:
            return f"Couldn't tailor your resume: {r.data.get('error')}", [], trace
        tips = [s.get("suggestion") or s.get("text") or "" for s in r.data.get("suggestions", [])]
        tips = [t for t in tips if t][:3]
        reply = f"Resume check for {r.data.get('job_title')}:"
        reply += ("\n" + "\n".join(f"• {t}" for t in tips)) if tips else " no rewrite suggestions — your resume already covers this job's keywords."
        return reply, r.cards, trace

    if (m := _EXPLAIN.search(text)) and ctx.last_list:
        r = _run(ctx, trace, "explain_match", {"job_ref": m.group(1)})
        if not r.ok:
            return f"Couldn't analyse that job: {r.data.get('error')}", [], trace
        d = r.data
        parts = [f"{d.get('title')}:"]
        if d.get("match_score") is not None:
            parts.append(f"{d['match_score']}% overall match.")
        missing = d.get("missing_required_skills") or []
        parts.append("Missing: " + ", ".join(missing[:4]) + "." if missing else "You cover the required skills.")
        if d.get("weakest_link"):
            parts.append(f"Weakest link: {d['weakest_link']}.")
        return " ".join(parts), r.cards, trace

    if re.search(r"\b(switch|transition|pivot|direction|target role|skills? (?:do i need|for)|gap)\b", low):
        r = _run(ctx, trace, "career_direction_gap", {})
        if not r.ok or "targets" not in r.data:
            return r.data.get("message") or r.data.get("error") or "Add target roles in your profile first.", r.cards, trace
        lines = []
        for t in r.data["targets"]:
            pct = f"{t['readiness_pct']}% ready" if t.get("readiness_pct") is not None else "no data yet"
            miss = ", ".join(t["top_missing"][:3]) or "nothing major"
            lines.append(f"• {t['target']}: {pct}; most-demanded gaps: {miss}")
        return "Here's how you stack up for your target roles:\n" + "\n".join(lines), r.cards, trace

    if re.search(r"\b(applied|applications?|tracker|saved jobs?|my saved|pipeline|status)\b", low):
        r = _run(ctx, trace, "list_my_applications", {})
        if not r.ok:
            return f"Couldn't load your tracker: {r.data.get('error')}", [], trace
        if not r.data["count"]:
            return "Your tracker is empty — save or apply to a job and it'll show up here.", r.cards, trace
        summary = ", ".join(f"{n} {s}" for s, n in r.data["by_status"].items())
        return f"You have {r.data['count']} tracked jobs ({summary}).", r.cards, trace

    if re.search(r"\b(recommend|suggest|for me|match(?:es)?|fit me|morning|digest|today)\b", low) or not text:
        r = _run(ctx, trace, "get_recommendations", {"limit": 5})
        if not r.ok:
            return f"Couldn't build your matches: {r.data.get('error')}", [], trace
        jobs = r.data.get("jobs") or []
        if not jobs:
            return "No matches yet — add skills or upload your resume and I'll rank jobs for you.", r.cards, trace
        reply = "Your top matches right now:\n" + _job_lines(jobs)
        if r.data.get("skill_gap_summary"):
            reply += f"\n\nPattern: {r.data['skill_gap_summary']}"
        return reply + "\n\nSay “why 2” for details or “save 1” to track one.", r.cards, trace

    # default: treat as a search
    location = None
    if m := _LOCATION.search(text):
        location = m.group(1)
    query = _FILLER.sub(" ", text if location is None else text.replace(location, " "))
    query = " ".join(query.split()) or text
    args: dict[str, Any] = {"query": query, "limit": 5}
    if location:
        args["location"] = location
    if "remote" in low:
        args["remote_only"] = True
    r = _run(ctx, trace, "search_jobs", args)
    if not r.ok:
        return f"Search failed: {r.data.get('error')}", [], trace
    jobs = r.data.get("jobs") or []
    if not jobs:
        return f"No jobs found for “{query}”. Try a broader role or drop the location.", r.cards, trace
    reply = f"Found {r.data.get('total_matches', len(jobs))} jobs for “{query}”. Top {len(jobs)}:\n" + _job_lines(jobs)
    if r.data.get("skill_gap_summary"):
        reply += f"\n\nPattern: {r.data['skill_gap_summary']}"
    return reply, r.cards, trace
