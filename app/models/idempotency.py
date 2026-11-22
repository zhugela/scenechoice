"""Short-lived claim records that make POST retries replay instead of repeat.

Why a table instead of an in-process cache
------------------------------------------
The same client retry can land on another worker or after a restart, and the
cost we are protecting against is a second model call plus a second archive.
Only a durable row can answer "has this key already been used?" across those
boundaries.

Lifecycle
---------
``pending``   A request owns the key and is generating. ``updated_at`` is the
              optimistic token the owner must present to complete/release it.
``completed`` The stored ``status_code`` and ``response_body`` are replayed
              verbatim. Completed rows are kept (no retention job yet).
A ``pending`` row older than the service's ten-minute timeout is treated as a
crashed attempt and may be reset by the next request with the same key.

Identity
--------
``(scope, key)`` is unique. ``scope`` names the endpoint (for example
``stories.create``) so two endpoints cannot collide merely because a client
reused the same human-readable key. ``fingerprint`` is the canonical request
hash: the same key with a different body is a client error, not a replay.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class IdempotencyRecord(Base):
    """One claim on an ``(scope, key)`` pair."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_records_scope_key"),
        CheckConstraint(
            "state IN ('pending', 'completed')",
            name="ck_idempotency_records_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- Filled in only when state == "completed" ---------------------------
    status_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # ``updated_at`` doubles as the pending-timeout clock and as the ownership
    # token: a request may only complete or release the row whose timestamp it
    # itself wrote.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
