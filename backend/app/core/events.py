"""Lightweight in-process event bus (event-driven hooks within the monolith).

For this single-DB application, domain events are dispatched in-process to
decouple side effects (logging, analytics, async work) from request handlers.
An external broker (Kafka/RabbitMQ/Redis Streams) can be added later behind the
same interface if the system is decomposed into services.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[["DomainEvent"], None]
_SUBSCRIBERS: dict[str, list[Handler]] = defaultdict(list)


@dataclass
class DomainEvent:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def subscribe(event_name: str, handler: Handler) -> None:
    _SUBSCRIBERS[event_name].append(handler)


def publish(event: DomainEvent) -> None:
    for handler in list(_SUBSCRIBERS.get(event.name, [])):
        try:
            handler(event)
        except Exception:
            log.exception("event handler failed for %s", event.name)
    # wildcard subscribers
    for handler in list(_SUBSCRIBERS.get("*", [])):
        try:
            handler(event)
        except Exception:
            log.exception("wildcard event handler failed for %s", event.name)
